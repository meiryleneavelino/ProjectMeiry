package governance

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
	"testing"
	"time"
)

type world struct {
	state map[string][]byte
	clock time.Time
	tx    int
	local *Config
}

type identity struct {
	world *world
	msp   string
	role  string
	admin bool
	id    string
}

func (i *identity) GetState(key string) ([]byte, error) { return i.world.state[key], nil }
func (i *identity) PutState(key string, value []byte) error {
	i.world.state[key] = append([]byte(nil), value...)
	return nil
}
func (i *identity) Range(prefix string) ([][]byte, error) {
	var keys []string
	for key := range i.world.state {
		if strings.HasPrefix(key, prefix) {
			keys = append(keys, key)
		}
	}
	sort.Strings(keys)
	values := make([][]byte, len(keys))
	for index, key := range keys {
		values[index] = i.world.state[key]
	}
	return values, nil
}
func (i *identity) MSPID() (string, error) { return i.msp, nil }
func (i *identity) Attribute(string) (string, bool, error) {
	return i.role, i.role != "", nil
}
func (i *identity) IsAdmin() (bool, error)        { return i.admin, nil }
func (i *identity) ClientID() (string, error)     { return i.id, nil }
func (i *identity) TxID() string                  { return fmt.Sprintf("%064x", i.world.tx) }
func (i *identity) Timestamp() (time.Time, error) { return i.world.clock, nil }
func (i *identity) LocalConfig() (*Config, error) { return i.world.local, nil }

func testConfig() *Config {
	digest := func(seed string) string { return "sha256:" + sha256Hex([]byte(seed)) }
	return &Config{
		Version: 1, Channel: "horus-governance",
		Organizations: map[string]string{"UVA": "UvaMSP", "VU": "VuMSP", "TUDELFT": "TudelftMSP"},
		RulesHash:     sha256Hex([]byte("rules")), PolicyHash: sha256Hex([]byte("policy")),
		SemgrepVersion: "1.145.0",
		AnalyzerImages: map[string]string{"UVA": digest("uva"), "VU": digest("vu"), "TUDELFT": digest("tudelft")},
		Rules: map[string]Rule{
			"horus.dynamic-code":   {Severity: "high", Message: "Dynamic evaluation or compilation is not permitted."},
			"horus.network-import": {Severity: "medium", Message: "Network-capable imports require removal before sandbox execution."},
		},
		Policy:               Policy{Deductions: map[string]int{"high": 25, "medium": 10, "low": 2}, MinimumScore: 70},
		RevealTimeoutSeconds: 600,
	}
}

func newWorld(t *testing.T) *world {
	w := &world{state: map[string][]byte{}, clock: time.Date(2026, 11, 3, 12, 0, 0, 0, time.UTC), local: testConfig()}
	raw, _ := json.Marshal(w.local)
	if _, err := w.as("TudelftMSP", "", true).call("InitConfig", string(raw)); err != nil {
		t.Fatal(err)
	}
	return w
}

func (w *world) as(msp, role string, admin bool) *identity {
	return &identity{world: w, msp: msp, role: role, admin: admin, id: "x509::" + msp + "::" + role}
}
func (w *world) researcher() *identity      { return w.as("TudelftMSP", RoleResearcher, false) }
func (w *world) agent(msp string) *identity { return w.as(msp, RoleAgent, false) }

func (i *identity) call(function string, args ...string) ([]byte, error) {
	i.world.tx++
	i.world.clock = i.world.clock.Add(time.Second)
	return Invoke(i, function, args)
}

func (i *identity) submission(t *testing.T, function string, args ...string) *Submission {
	t.Helper()
	raw, err := i.call(function, args...)
	if err != nil {
		t.Fatalf("%s: %v", function, err)
	}
	var submission Submission
	if err := json.Unmarshal(raw, &submission); err != nil {
		t.Fatal(err)
	}
	return &submission
}

func kind(err error) string {
	var typed *Error
	if errors.As(err, &typed) {
		return typed.Kind
	}
	return ""
}

func secretFor(organization string) (string, string) {
	sum := sha256.Sum256([]byte("secret-" + organization))
	secret := hex.EncodeToString(sum[:])
	return secret, sha256Hex(sum[:])
}

var msps = map[string]string{"UVA": "UvaMSP", "VU": "VuMSP", "TUDELFT": "TudelftMSP"}

func drawn(t *testing.T, w *world, codeHash string) *Submission {
	t.Helper()
	for _, organization := range []string{"UVA", "VU"} {
		_, commitment := secretFor(organization)
		w.agent(msps[organization]).submission(t, "CommitSeed", codeHash, commitment)
	}
	var last *Submission
	for _, organization := range []string{"UVA", "VU"} {
		secret, _ := secretFor(organization)
		last = w.agent(msps[organization]).submission(t, "RevealSeed", codeHash, secret)
	}
	return last
}

func cleanReport(config *Config, codeHash string) (string, string) {
	value := map[string]any{
		"schema_version": 1, "code_hash": codeHash, "rules_hash": config.RulesHash, "policy_hash": config.PolicyHash,
		"semgrep_version": config.SemgrepVersion, "score": 100, "counts": map[string]int{"high": 0, "medium": 0, "low": 0},
		"findings": []any{}, "decision": "approved",
		"reasons": []string{"No high-severity findings and security score meets policy."},
	}
	raw, _ := json.Marshal(value)
	return string(raw), sha256Hex(raw)
}

func TestConfigMustMatchEveryOrganizationsLocalFile(t *testing.T) {
	w := newWorld(t)
	other := testConfig()
	other.Policy.MinimumScore = 0
	raw, _ := json.Marshal(other)
	if _, err := w.as("UvaMSP", "", true).call("InitConfig", string(raw)); kind(err) != "forbidden" {
		t.Fatalf("a different configuration must be refused, got %v", err)
	}
	same, _ := json.Marshal(w.local)
	if _, err := w.as("UvaMSP", RoleAgent, false).call("InitConfig", string(same)); kind(err) != "forbidden" {
		t.Fatalf("non-admins cannot initialize, got %v", err)
	}
}

func TestOrganizationComesFromCertificateAndResearcherIsExcluded(t *testing.T) {
	w := newWorld(t)
	submission := w.researcher().submission(t, "SubmitCode", "value = 1\n", `["UVA","VU","TUDELFT"]`)
	if submission.ResearcherOrg != "TUDELFT" || strings.Join(submission.Eligible, ",") != "UVA,VU" {
		t.Fatalf("unexpected eligibility %+v", submission)
	}
	if submission.Status != StatusDrawing || submission.Reviewer != "" {
		t.Fatalf("server must not choose the reviewer: %+v", submission)
	}
	if _, err := w.agent("UvaMSP").call("SubmitCode", "value = 2\n", `["VU"]`); kind(err) != "forbidden" {
		t.Fatalf("agents cannot submit code, got %v", err)
	}
	if _, err := w.researcher().call("SubmitCode", "value = 1\n", `["UVA"]`); kind(err) != "conflict" {
		t.Fatalf("duplicate hash must conflict, got %v", err)
	}
	if _, err := w.researcher().call("SubmitCode", "value = 3\n", `["TUDELFT"]`); kind(err) != "invalid" {
		t.Fatalf("researcher-only selection has no reviewer, got %v", err)
	}
	if _, err := w.researcher().call("SubmitCode", "value = 4\r\n", `["UVA"]`); kind(err) != "invalid" {
		t.Fatalf("non-normalized code must be refused, got %v", err)
	}
}

func TestCommitRevealDrawIsRecomputable(t *testing.T) {
	w := newWorld(t)
	submission := w.researcher().submission(t, "SubmitCode", "value = 1\n", `["UVA","VU","TUDELFT"]`)
	secret, _ := secretFor("UVA")
	if _, err := w.agent("UvaMSP").call("RevealSeed", submission.CodeHash, secret); kind(err) != "conflict" {
		t.Fatalf("reveal before commit must fail, got %v", err)
	}
	_, commitment := secretFor("UVA")
	w.agent("UvaMSP").submission(t, "CommitSeed", submission.CodeHash, commitment)
	if _, err := w.agent("UvaMSP").call("RevealSeed", submission.CodeHash, secret); kind(err) != "conflict" {
		t.Fatalf("reveal must wait for all commits, got %v", err)
	}
	if _, err := w.agent("TudelftMSP").call("CommitSeed", submission.CodeHash, commitment); kind(err) != "forbidden" {
		t.Fatalf("researcher organization cannot take part in the draw, got %v", err)
	}
	_, vuCommitment := secretFor("VU")
	w.agent("VuMSP").submission(t, "CommitSeed", submission.CodeHash, vuCommitment)
	if _, err := w.agent("UvaMSP").call("RevealSeed", submission.CodeHash, strings.Repeat("0", 64)); kind(err) != "invalid" {
		t.Fatalf("wrong secret must fail, got %v", err)
	}
	w.agent("UvaMSP").submission(t, "RevealSeed", submission.CodeHash, secret)
	vuSecret, _ := secretFor("VU")
	final := w.agent("VuMSP").submission(t, "RevealSeed", submission.CodeHash, vuSecret)
	if final.Status != StatusAssigned || final.SelectionVersion != SelectionCommitReveal {
		t.Fatalf("draw did not close: %+v", final)
	}
	material, _ := hex.DecodeString(final.CodeHash)
	for _, value := range []string{secret, vuSecret} {
		raw, _ := hex.DecodeString(value)
		material = append(material, raw...)
	}
	seed := sha256.Sum256(material)
	expected, best := "", ""
	for _, organization := range []string{"UVA", "VU"} {
		rank := sha256Hex(append(seed[:], []byte(organization)...))
		if expected == "" || rank < best {
			expected, best = organization, rank
		}
	}
	if final.Seed != hex.EncodeToString(seed[:]) || final.Reviewer != expected {
		t.Fatalf("anyone must be able to recompute the draw: %+v", final)
	}
}

func TestSingleEligibleOrganizationIsAssignedDirectly(t *testing.T) {
	w := newWorld(t)
	submission := w.researcher().submission(t, "SubmitCode", "value = 1\n", `["UVA","TUDELFT"]`)
	if submission.Status != StatusAssigned || submission.Reviewer != "UVA" || submission.SelectionVersion != SelectionSingle {
		t.Fatalf("single eligible organization must be assigned: %+v", submission)
	}
}

func TestTimeoutExcludesOrganizationThatDidNotReveal(t *testing.T) {
	w := newWorld(t)
	submission := w.researcher().submission(t, "SubmitCode", "value = 1\n", `["UVA","VU","TUDELFT"]`)
	_, commitment := secretFor("UVA")
	w.agent("UvaMSP").submission(t, "CommitSeed", submission.CodeHash, commitment)
	secret, _ := secretFor("UVA")
	w.clock = w.clock.Add(11 * time.Minute)
	w.agent("UvaMSP").submission(t, "RevealSeed", submission.CodeHash, secret)
	if _, err := w.agent("VuMSP").call("ForceDraw", submission.CodeHash); kind(err) != "forbidden" {
		t.Fatalf("an organization that did not reveal cannot force the draw, got %v", err)
	}
	final := w.agent("UvaMSP").submission(t, "ForceDraw", submission.CodeHash)
	if final.Reviewer != "UVA" || strings.Join(final.Defaulted, ",") != "VU" || final.SelectionVersion != SelectionTimeout {
		t.Fatalf("defaulted organization must be excluded: %+v", final)
	}
}

func TestOnlyDrawnReviewerRecordsAndReportIsRecomputed(t *testing.T) {
	w := newWorld(t)
	submission := w.researcher().submission(t, "SubmitCode", "value = 1\n", `["UVA","VU","TUDELFT"]`)
	assigned := drawn(t, w, submission.CodeHash)
	reviewer, other := assigned.Reviewer, "UVA"
	if reviewer == "UVA" {
		other = "VU"
	}
	reportJSON, reportHash := cleanReport(w.local, submission.CodeHash)
	if _, err := w.agent(msps[other]).call("RecordAnalysis", submission.CodeHash, reportJSON, reportHash,
		w.local.AnalyzerImages[other]); kind(err) != "forbidden" {
		t.Fatalf("a non-drawn organization must be refused, got %v", err)
	}
	if _, err := w.agent(msps[reviewer]).call("RecordAnalysis", submission.CodeHash, reportJSON, reportHash,
		w.local.AnalyzerImages[other]); kind(err) != "invalid" {
		t.Fatalf("another organization's image must be refused, got %v", err)
	}
	var tampered map[string]any
	_ = json.Unmarshal([]byte(reportJSON), &tampered)
	tampered["findings"] = []map[string]any{{"rule_id": "horus.dynamic-code", "line": 1, "column": 1,
		"severity": "high", "message": "Dynamic evaluation or compilation is not permitted."}}
	raw, _ := json.Marshal(tampered)
	if _, err := w.agent(msps[reviewer]).call("RecordAnalysis", submission.CodeHash, string(raw), sha256Hex(raw),
		w.local.AnalyzerImages[reviewer]); kind(err) != "invalid" {
		t.Fatalf("approval with a high finding must be refused, got %v", err)
	}
	if _, err := w.agent(msps[reviewer]).call("RecordAnalysis", submission.CodeHash, reportJSON, strings.Repeat("a", 64),
		w.local.AnalyzerImages[reviewer]); kind(err) != "invalid" {
		t.Fatalf("wrong report hash must be refused, got %v", err)
	}
	approved := w.agent(msps[reviewer]).submission(t, "RecordAnalysis", submission.CodeHash, reportJSON, reportHash,
		w.local.AnalyzerImages[reviewer])
	if approved.Status != StatusApproved || approved.Analysis.Organization != reviewer {
		t.Fatalf("analysis not recorded: %+v", approved)
	}
	if _, err := w.agent(msps[reviewer]).call("RecordAnalysis", submission.CodeHash, reportJSON, reportHash,
		w.local.AnalyzerImages[reviewer]); kind(err) != "conflict" {
		t.Fatalf("analysis must be recorded only once, got %v", err)
	}
}

func TestAuditMismatchDisputesApproval(t *testing.T) {
	w := newWorld(t)
	submission := w.researcher().submission(t, "SubmitCode", "value = 1\n", `["UVA","VU","TUDELFT"]`)
	assigned := drawn(t, w, submission.CodeHash)
	reviewer, auditor := assigned.Reviewer, "UVA"
	if reviewer == "UVA" {
		auditor = "VU"
	}
	reportJSON, reportHash := cleanReport(w.local, submission.CodeHash)
	w.agent(msps[reviewer]).submission(t, "RecordAnalysis", submission.CodeHash, reportJSON, reportHash, w.local.AnalyzerImages[reviewer])
	if _, err := w.agent(msps[reviewer]).call("AuditAnalysis", submission.CodeHash, reportHash, w.local.AnalyzerImages[reviewer]); kind(err) != "forbidden" {
		t.Fatalf("reviewer cannot audit itself, got %v", err)
	}
	audited := w.agent(msps[auditor]).submission(t, "AuditAnalysis", submission.CodeHash, strings.Repeat("b", 64), w.local.AnalyzerImages[auditor])
	if !audited.Disputed || audited.Audits[0].Match {
		t.Fatalf("mismatch must dispute: %+v", audited)
	}
	raw, _ := w.researcher().call("IsApproved", submission.CodeHash)
	var approval map[string]any
	_ = json.Unmarshal(raw, &approval)
	if approval["approved"] != false {
		t.Fatalf("a disputed approval is not usable: %v", approval)
	}
}

func TestTrainingStartIsIdempotentAndEventsHaveNoCode(t *testing.T) {
	w := newWorld(t)
	w.researcher().submission(t, "SubmitCode", "marker_not_for_events = 1\n", `["UVA"]`)
	run := "0b6f1a52-3b0c-4b8e-9d7e-1f0a2c3d4e5f"
	first, err := w.researcher().call("RecordTrainingStart", run, Builtin, `["UVA","VU"]`)
	if err != nil {
		t.Fatal(err)
	}
	second, err := w.researcher().call("RecordTrainingStart", run, Builtin, `["UVA","VU"]`)
	if err != nil || string(first) != string(second) {
		t.Fatalf("retry must return the original record: %v", err)
	}
	if _, err := w.researcher().call("RecordTrainingStart", run, Builtin, `["UVA","TUDELFT"]`); kind(err) != "conflict" {
		t.Fatalf("changed parameters must conflict, got %v", err)
	}
	events, _ := w.researcher().call("ListEvents")
	if strings.Contains(string(events), "marker_not_for_events") {
		t.Fatal("events must never contain code text")
	}
	var list []Event
	_ = json.Unmarshal(events, &list)
	if list[len(list)-1].EventType != "TrainingStarted" {
		t.Fatalf("events must be ordered by transaction time: %+v", list)
	}
}

func TestResearcherCannotRecordAnalysis(t *testing.T) {
	w := newWorld(t)
	submission := w.researcher().submission(t, "SubmitCode", "value = 1\n", `["UVA","TUDELFT"]`)
	report, hash := cleanReport(w.local, submission.CodeHash)
	if _, err := w.researcher().call("RecordAnalysis", submission.CodeHash, report, hash,
		w.local.AnalyzerImages["UVA"]); kind(err) != "forbidden" {
		t.Fatalf("expected forbidden, got %v", err)
	}
}
