package agent

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"testing"
	"time"

	"horus-ledger/governance"
	"horus-ledger/internal/memledger"
)

var msps = map[string]string{"UVA": "UvaMSP", "VU": "VuMSP", "TUDELFT": "TudelftMSP"}

func digest(organization string) string {
	sum := sha256.Sum256([]byte("image-" + organization))
	return "sha256:" + hex.EncodeToString(sum[:])
}

func config() *governance.Config {
	images := map[string]string{}
	for organization := range msps {
		images[organization] = digest(organization)
	}
	return &governance.Config{
		Version: 1, Channel: "horus-governance", Organizations: msps,
		RulesHash: sha256Hex([]byte("rules")), PolicyHash: sha256Hex([]byte("policy")), SemgrepVersion: "1.145.0",
		AnalyzerImages: images,
		Rules: map[string]governance.Rule{"horus.dynamic-code": {Severity: "high",
			Message: "Dynamic evaluation or compilation is not permitted."}},
		Policy:               governance.Policy{Deductions: map[string]int{"high": 25, "medium": 10, "low": 2}, MinimumScore: 70},
		RevealTimeoutSeconds: 600,
	}
}

// fakeRunner mimics the analyzer container: canonical JSON on stdout.
type fakeRunner struct {
	organization string
	config       *governance.Config
	tamper       bool
	runs         int
}

func (f *fakeRunner) Run(_ context.Context, codeHash string, code []byte) ([]byte, string, error) {
	f.runs++
	if sha256Hex(code) != codeHash {
		return nil, "", fmt.Errorf("runner received wrong code")
	}
	findings, counts, score, decision, reasons := []any{}, map[string]int{"high": 0, "low": 0, "medium": 0}, 100,
		"approved", []string{"No high-severity findings and security score meets policy."}
	if f.tamper {
		findings = []any{map[string]any{"column": 1, "line": 1, "message": "Dynamic evaluation or compilation is not permitted.",
			"rule_id": "horus.dynamic-code", "severity": "high"}}
		counts["high"], score, decision = 1, 75, "rejected"
		reasons = []string{"High-severity findings are not permitted."}
	}
	report, _ := json.Marshal(map[string]any{"code_hash": codeHash, "counts": counts, "decision": decision,
		"findings": findings, "policy_hash": f.config.PolicyHash, "reasons": reasons, "rules_hash": f.config.RulesHash,
		"schema_version": 1, "score": score, "semgrep_version": f.config.SemgrepVersion})
	output := fmt.Sprintf("warning on stderr\n{\"provenance\":{\"organization\":%q},\"report\":%s,\"report_hash\":%q}\n",
		f.organization, report, sha256Hex(report))
	return []byte(output), digest(f.organization), nil
}

func agents(t *testing.T, world *memledger.World, tamper string) map[string]*Agent {
	result := map[string]*Agent{}
	for organization, msp := range msps {
		result[organization] = &Agent{Organization: organization, StateDir: t.TempDir(), Audit: true,
			Ledger: world.As(msp, governance.RoleAgent, false), Config: world.Local,
			Runner: &fakeRunner{organization: organization, config: world.Local, tamper: organization == tamper},
			Now:    func() time.Time { return world.Clock }}
	}
	return result
}

func settle(world *memledger.World, team map[string]*Agent) {
	for round := 0; round < 8; round++ {
		for _, organization := range []string{"UVA", "VU", "TUDELFT"} {
			team[organization].Tick(context.Background())
		}
	}
}

func submit(t *testing.T, world *memledger.World) string {
	researcher := world.As("TudelftMSP", governance.RoleResearcher, false)
	raw, _, err := researcher.Submit("SubmitCode", "value = 1\n", `["UVA","VU","TUDELFT"]`)
	if err != nil {
		t.Fatal(err)
	}
	var submission governance.Submission
	_ = json.Unmarshal(raw, &submission)
	return submission.CodeHash
}

func load(t *testing.T, world *memledger.World, hash string) governance.Submission {
	raw, err := world.As("UvaMSP", governance.RoleAgent, false).Evaluate("GetSubmission", hash)
	if err != nil {
		t.Fatal(err)
	}
	var submission governance.Submission
	_ = json.Unmarshal(raw, &submission)
	return submission
}

func TestAgentsDrawAnalyzeAndAuditEndToEnd(t *testing.T) {
	world, err := memledger.New(config())
	if err != nil {
		t.Fatal(err)
	}
	team := agents(t, world, "")
	hash := submit(t, world)
	settle(world, team)
	submission := load(t, world, hash)
	if submission.Status != governance.StatusApproved || submission.Analysis == nil {
		t.Fatalf("expected approved analysis, got %+v", submission)
	}
	if submission.Analysis.Organization != submission.Reviewer || submission.Reviewer == "TUDELFT" {
		t.Fatalf("analysis must come from the drawn non-researcher reviewer: %+v", submission)
	}
	if len(submission.Audits) != 1 || !submission.Audits[0].Match || submission.Disputed {
		t.Fatalf("the other eligible organization must audit and match: %+v", submission.Audits)
	}
	if team["TUDELFT"].Runner.(*fakeRunner).runs != 0 {
		t.Fatal("the researcher's organization must not analyze or audit its own submission")
	}
	if err := VerifyConfig(team["UVA"].Ledger, world.Local); err != nil {
		t.Fatal(err)
	}
}

func TestDishonestReviewerIsCaughtByAudit(t *testing.T) {
	world, err := memledger.New(config())
	if err != nil {
		t.Fatal(err)
	}
	hash := submit(t, world)
	// First find out who will be drawn, then make exactly that organization lie.
	probe := agents(t, world, "")
	for _, organization := range []string{"UVA", "VU"} {
		probe[organization].Tick(context.Background())
	}
	for _, organization := range []string{"UVA", "VU"} {
		probe[organization].Tick(context.Background())
	}
	reviewer := load(t, world, hash).Reviewer
	team := agents(t, world, reviewer)
	for organization := range team {
		team[organization].StateDir = probe[organization].StateDir
	}
	settle(world, team)
	submission := load(t, world, hash)
	if submission.Status != governance.StatusRejected || !submission.Disputed {
		t.Fatalf("a report that differs from an independent re-run must be disputed: %+v", submission)
	}
}

func TestConfigMismatchStopsAgent(t *testing.T) {
	world, err := memledger.New(config())
	if err != nil {
		t.Fatal(err)
	}
	changed := config()
	changed.Policy.MinimumScore = 0
	if err := VerifyConfig(world.As("UvaMSP", governance.RoleAgent, false), changed); err == nil {
		t.Fatal("an agent must refuse a ledger configuration it did not agree to")
	}
}

// flakyRunner reports an infrastructure error on its first run only.
type flakyRunner struct {
	fakeRunner
	failed bool
}

func (f *flakyRunner) Run(ctx context.Context, codeHash string, code []byte) ([]byte, string, error) {
	if !f.failed {
		f.failed = true
		return []byte(`{"error":{"code":"scanner_unavailable","message":"x"}}`), digest(f.organization), nil
	}
	return f.fakeRunner.Run(ctx, codeHash, code)
}

func TestTransientFailureIsRetriedButInputErrorsAreFinal(t *testing.T) {
	world, err := memledger.New(config())
	if err != nil {
		t.Fatal(err)
	}
	team := agents(t, world, "")
	team["UVA"].Runner = &flakyRunner{fakeRunner: fakeRunner{organization: "UVA", config: world.Local}}
	researcher := world.As("TudelftMSP", governance.RoleResearcher, false)
	raw, _, err := researcher.Submit("SubmitCode", "value = 1\n", `["UVA","TUDELFT"]`)
	if err != nil {
		t.Fatal(err)
	}
	var submission governance.Submission
	_ = json.Unmarshal(raw, &submission)
	team["UVA"].Tick(context.Background())
	if state := load(t, world, submission.CodeHash); state.Status != governance.StatusError {
		t.Fatalf("first run must record the failure, got %s", state.Status)
	}
	team["UVA"].Tick(context.Background())
	if state := load(t, world, submission.CodeHash); state.Status != governance.StatusApproved || state.Failure != nil {
		t.Fatalf("transient failure must be retried, got %+v", state)
	}
}
