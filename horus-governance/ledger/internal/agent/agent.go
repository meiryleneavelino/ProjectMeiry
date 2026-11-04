// Package agent is the organization-local SAST agent. One instance runs in
// each organization's namespace with that organization's identity. It only
// talks to its own peer and only creates analysis Jobs in its own namespace.
package agent

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"time"

	"horus-ledger/governance"
	"horus-ledger/internal/fabclient"
)

// Ledger is the subset of the Fabric client the agent needs (mocked in tests).
type Ledger interface {
	Evaluate(function string, args ...string) ([]byte, error)
	Submit(function string, args ...string) ([]byte, fabclient.Receipt, error)
}

// Runner executes the analyzer on code and returns its stdout and image digest.
type Runner interface {
	Run(ctx context.Context, codeHash string, code []byte) (output []byte, digest string, err error)
}

type Agent struct {
	Organization string
	StateDir     string
	Audit        bool
	Ledger       Ledger
	Runner       Runner
	Config       *governance.Config
	Now          func() time.Time
	attempts     map[string]int
}

const maxAttempts = 3

// transient failure codes come from infrastructure, not from the submitted text.
var transient = map[string]bool{"analysis_unavailable": true, "scanner_unavailable": true,
	"scanner_failed": true, "analysis_failed": true, "incomplete_scan": true, "invalid_scanner_output": true}

// VerifyConfig refuses to work when the ledger configuration differs from the
// configuration this organization agreed to (rules, policy, images, members).
func VerifyConfig(ledger Ledger, local *governance.Config) error {
	raw, err := ledger.Evaluate("GetConfig")
	if err != nil {
		return err
	}
	var active governance.Config
	if err := json.Unmarshal(raw, &active); err != nil {
		return err
	}
	activeBytes, _ := json.Marshal(active)
	localBytes, _ := json.Marshal(local)
	if !bytes.Equal(activeBytes, localBytes) {
		return errors.New("ledger configuration differs from this organization's agreed configuration")
	}
	return nil
}

func sha256Hex(value []byte) string {
	sum := sha256.Sum256(value)
	return hex.EncodeToString(sum[:])
}

// Tick performs at most one action per submission and returns how many
// actions succeeded. Failed actions are retried on the next tick.
func (a *Agent) Tick(ctx context.Context) int {
	if a.attempts == nil {
		a.attempts = map[string]int{}
	}
	raw, err := a.Ledger.Evaluate("ListSubmissions")
	if err != nil {
		log.Printf("list submissions failed: %v", err)
		return 0
	}
	var submissions []governance.Submission
	if err := json.Unmarshal(raw, &submissions); err != nil {
		log.Printf("invalid submission list: %v", err)
		return 0
	}
	done := 0
	for index := range submissions {
		submission := &submissions[index]
		if !contains(submission.Eligible, a.Organization) {
			continue
		}
		if err := a.step(ctx, submission); err != nil {
			log.Printf("%s: %v", submission.CodeHash[:12], err)
		} else {
			done++
		}
	}
	return done
}

func contains(values []string, value string) bool {
	for _, candidate := range values {
		if candidate == value {
			return true
		}
	}
	return false
}

var errNothing = errors.New("nothing to do")

func (a *Agent) step(ctx context.Context, submission *governance.Submission) error {
	err := a.decide(ctx, submission)
	if errors.Is(err, errNothing) {
		return nil
	}
	return err
}

func (a *Agent) decide(ctx context.Context, submission *governance.Submission) error {
	switch submission.Status {
	case governance.StatusDrawing:
		return a.draw(submission)
	case governance.StatusAssigned:
		if submission.Reviewer == a.Organization {
			return a.review(ctx, submission)
		}
	case governance.StatusError:
		// Infrastructure failures may be retried by the same reviewer (the
		// chaincode accepts RecordAnalysis after an error); input errors such as
		// invalid_python are final because a re-run gives the same answer.
		if submission.Reviewer == a.Organization && submission.Failure != nil && transient[submission.Failure.Code] {
			return a.review(ctx, submission)
		}
	case governance.StatusApproved, governance.StatusRejected:
		if a.Audit && submission.Analysis != nil && submission.Reviewer != a.Organization && !audited(submission, a.Organization) {
			return a.audit(ctx, submission)
		}
	}
	return errNothing
}

func audited(submission *governance.Submission, organization string) bool {
	for _, item := range submission.Audits {
		if item.Organization == organization {
			return true
		}
	}
	return false
}

// secret returns this organization's private random value for one draw.
// It is written to the agent's own volume before the commitment is sent, so a
// restart between commit and reveal can still open the commitment.
func (a *Agent) secret(codeHash string, create bool) (string, error) {
	directory := filepath.Join(a.StateDir, "secrets")
	path := filepath.Join(directory, codeHash)
	if raw, err := os.ReadFile(path); err == nil {
		return string(bytes.TrimSpace(raw)), nil
	} else if !create {
		return "", fmt.Errorf("local draw secret is missing")
	}
	if err := os.MkdirAll(directory, 0o700); err != nil {
		return "", err
	}
	value := make([]byte, 32)
	if _, err := rand.Read(value); err != nil {
		return "", err
	}
	secret := hex.EncodeToString(value)
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return "", err
	}
	if _, err := file.WriteString(secret); err != nil {
		file.Close()
		return "", err
	}
	if err := file.Sync(); err != nil {
		file.Close()
		return "", err
	}
	return secret, file.Close()
}

func (a *Agent) expired(submission *governance.Submission) bool {
	created, err := time.Parse("2006-01-02T15:04:05.000000000Z", submission.CreatedAt)
	if err != nil {
		return false
	}
	// A small margin so this organization's clock does not run ahead of the
	// transaction timestamp checked by the chaincode.
	return a.Now().Sub(created) > time.Duration(a.Config.RevealTimeoutSeconds+5)*time.Second
}

func (a *Agent) draw(submission *governance.Submission) error {
	hash, organization := submission.CodeHash, a.Organization
	if _, committed := submission.Commits[organization]; !committed {
		if len(submission.Reveals) > 0 {
			return errNothing
		}
		secret, err := a.secret(hash, true)
		if err != nil {
			return err
		}
		raw, _ := hex.DecodeString(secret)
		_, receipt, err := a.Ledger.Submit("CommitSeed", hash, sha256Hex(raw))
		if err == nil {
			log.Printf("%s: committed draw seed (tx %s, block %d)", hash[:12], receipt.TxID[:12], receipt.BlockNumber)
		}
		return err
	}
	if _, revealed := submission.Reveals[organization]; !revealed {
		if len(submission.Commits) < len(submission.Eligible) && !a.expired(submission) {
			return errNothing
		}
		secret, err := a.secret(hash, false)
		if err != nil {
			return err
		}
		_, receipt, err := a.Ledger.Submit("RevealSeed", hash, secret)
		if err == nil {
			log.Printf("%s: revealed draw seed (tx %s, block %d)", hash[:12], receipt.TxID[:12], receipt.BlockNumber)
		}
		return err
	}
	if a.expired(submission) {
		_, receipt, err := a.Ledger.Submit("ForceDraw", hash)
		if err == nil {
			log.Printf("%s: closed stalled draw after timeout (tx %s)", hash[:12], receipt.TxID[:12])
		}
		return err
	}
	return errNothing
}

type envelope struct {
	Report     json.RawMessage `json:"report"`
	ReportHash string          `json:"report_hash"`
	Provenance struct {
		Organization string `json:"organization"`
	} `json:"provenance"`
	Error *struct {
		Code string `json:"code"`
	} `json:"error"`
}

var lastJSON = regexp.MustCompile(`(?m)^\{.*\}\s*$`)

// analysis is the verified result of one local run.
type analysis struct {
	reportJSON string
	reportHash string
	digest     string
	failure    string // deterministic analyzer error code, e.g. invalid_python
}

// analyze fetches the code from its own peer, checks it against the hash on
// the ledger, runs the ephemeral Job and verifies the report envelope.
func (a *Agent) analyze(ctx context.Context, codeHash string) (*analysis, error) {
	code, err := a.Ledger.Evaluate("GetCode", codeHash)
	if err != nil {
		return nil, err
	}
	if sha256Hex(code) != codeHash {
		return nil, errors.New("code returned by the peer does not match the ledger hash")
	}
	output, digest, err := a.Runner.Run(ctx, codeHash, code)
	if err != nil {
		return nil, err
	}
	matches := lastJSON.FindAll(output, -1)
	if len(matches) == 0 {
		return nil, errors.New("analyzer produced no JSON result")
	}
	var result envelope
	if err := json.Unmarshal(matches[len(matches)-1], &result); err != nil {
		return nil, errors.New("analyzer result is not valid JSON")
	}
	if result.Error != nil {
		return &analysis{failure: result.Error.Code, digest: digest}, nil
	}
	// The analyzer prints canonical JSON, so the raw "report" bytes are exactly
	// the bytes whose SHA-256 is report_hash; no re-serialization is involved.
	var parsed struct {
		CodeHash string `json:"code_hash"`
	}
	if err := json.Unmarshal(result.Report, &parsed); err != nil || sha256Hex(result.Report) != result.ReportHash ||
		parsed.CodeHash != codeHash || result.Provenance.Organization != a.Organization {
		return nil, errors.New("analyzer report failed local verification")
	}
	if digest != a.Config.AnalyzerImages[a.Organization] {
		return nil, fmt.Errorf("analysis ran on image %s, not the agreed image", digest)
	}
	return &analysis{reportJSON: string(result.Report), reportHash: result.ReportHash, digest: digest}, nil
}

func (a *Agent) attempt(key string) bool {
	a.attempts[key]++
	return a.attempts[key] <= maxAttempts
}

func (a *Agent) review(ctx context.Context, submission *governance.Submission) error {
	hash := submission.CodeHash
	retry := submission.Status == governance.StatusError
	if !a.attempt("review:" + hash) {
		if retry {
			return errNothing // the failure is already on the ledger
		}
		_, _, err := a.Ledger.Submit("RecordAnalysisFailure", hash, "analysis_unavailable")
		if err == nil {
			log.Printf("%s: recorded analysis failure after %d attempts", hash[:12], maxAttempts)
		}
		return err
	}
	result, err := a.analyze(ctx, hash)
	if err != nil {
		return err
	}
	if result.failure != "" {
		if retry {
			return fmt.Errorf("retry failed again with %s", result.failure)
		}
		_, receipt, err := a.Ledger.Submit("RecordAnalysisFailure", hash, result.failure)
		if err == nil {
			log.Printf("%s: analyzer rejected input (%s), recorded in tx %s", hash[:12], result.failure, receipt.TxID[:12])
		}
		return err
	}
	_, receipt, err := a.Ledger.Submit("RecordAnalysis", hash, result.reportJSON, result.reportHash, result.digest)
	if err == nil {
		log.Printf("%s: recorded signed analysis %s (tx %s, block %d)", hash[:12], result.reportHash[:12],
			receipt.TxID[:12], receipt.BlockNumber)
	}
	return err
}

func (a *Agent) audit(ctx context.Context, submission *governance.Submission) error {
	hash := submission.CodeHash
	if !a.attempt("audit:" + hash) {
		return errNothing
	}
	result, err := a.analyze(ctx, hash)
	if err != nil {
		return err
	}
	if result.failure != "" {
		return fmt.Errorf("audit analyzer error %s; not recorded", result.failure)
	}
	_, receipt, err := a.Ledger.Submit("AuditAnalysis", hash, result.reportHash, result.digest)
	if err == nil {
		log.Printf("%s: audit recorded, match=%t (tx %s)", hash[:12], result.reportHash == submission.Analysis.ReportHash,
			receipt.TxID[:12])
	}
	return err
}

// Loop runs until the context is cancelled.
func (a *Agent) Loop(ctx context.Context, interval time.Duration) {
	for {
		a.Tick(ctx)
		select {
		case <-ctx.Done():
			return
		case <-time.After(interval):
		}
	}
}

func EnvBool(name string, fallback bool) bool {
	if value, err := strconv.ParseBool(os.Getenv(name)); err == nil {
		return value
	}
	return fallback
}
