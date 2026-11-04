// Package governance holds the deterministic rules of the Horus governance
// chaincode. It has no Fabric dependency so it can be tested in memory; the
// chaincode adapter in internal/chaincode connects it to the peer shim.
package governance

import "time"

const (
	// Builtin is the trusted baseline algorithm that never needs analysis.
	Builtin = "logistic-regression-v1"
	// MaxCodeBytes keeps the code plus Kubernetes overhead inside one ConfigMap.
	MaxCodeBytes = 900 * 1024

	RoleAttribute  = "horus.role"
	RoleResearcher = "researcher"
	RoleAgent      = "reviewer-agent"

	SelectionSingle       = "single-eligible-v1"
	SelectionCommitReveal = "commit-reveal-sha256-rank-v1"
	SelectionTimeout      = "commit-reveal-timeout-v1"

	StatusDrawing  = "drawing"
	StatusAssigned = "assigned"
	StatusApproved = "approved"
	StatusRejected = "rejected"
	StatusError    = "error"

	timeLayout = "2006-01-02T15:04:05.000000000Z"
)

// Rule is the public part of one Semgrep rule that the chaincode needs to
// validate a report: its severity and fixed message.
type Rule struct {
	Severity string `json:"severity"`
	Message  string `json:"message"`
}

// Policy mirrors config/policy.json scoring fields.
type Policy struct {
	Deductions          map[string]int `json:"deductions"`
	MinimumScore        int            `json:"minimum_score"`
	MaximumHighFindings int            `json:"maximum_high_findings"`
}

// Config is agreed by every organization. Each organization's chaincode
// container receives the same file and refuses any other value in InitConfig.
type Config struct {
	Version              int               `json:"version"`
	Channel              string            `json:"channel"`
	Organizations        map[string]string `json:"organizations"`
	RulesHash            string            `json:"rules_hash"`
	PolicyHash           string            `json:"policy_hash"`
	SemgrepVersion       string            `json:"semgrep_version"`
	AnalyzerImages       map[string]string `json:"analyzer_images"`
	Rules                map[string]Rule   `json:"rules"`
	Policy               Policy            `json:"policy"`
	RevealTimeoutSeconds int               `json:"reveal_timeout_seconds"`
}

// Analysis is the signed result recorded by the drawn reviewer.
type Analysis struct {
	Organization string `json:"organization"`
	MSPID        string `json:"msp_id"`
	ReportJSON   string `json:"report_json"`
	ReportHash   string `json:"report_hash"`
	Decision     string `json:"decision"`
	Score        int    `json:"score"`
	ImageDigest  string `json:"image_digest"`
	TxID         string `json:"tx_id"`
	RecordedAt   string `json:"recorded_at"`
}

// Failure is recorded when the reviewer could not produce a report.
type Failure struct {
	Organization string `json:"organization"`
	Code         string `json:"code"`
	TxID         string `json:"tx_id"`
	RecordedAt   string `json:"recorded_at"`
}

// Audit is an independent re-execution by another eligible organization.
type Audit struct {
	Organization string `json:"organization"`
	ReportHash   string `json:"report_hash"`
	ImageDigest  string `json:"image_digest"`
	Match        bool   `json:"match"`
	TxID         string `json:"tx_id"`
	RecordedAt   string `json:"recorded_at"`
}

// Submission is the public state of one submitted code hash. The code text
// itself is stored under a separate key and never returned by list queries.
type Submission struct {
	CodeHash         string            `json:"code_hash"`
	CodeBytes        int               `json:"code_bytes"`
	Status           string            `json:"status"`
	ResearcherOrg    string            `json:"researcher_org"`
	ResearcherID     string            `json:"researcher_id"`
	Selected         []string          `json:"selected"`
	Eligible         []string          `json:"eligible"`
	CreatedAt        string            `json:"created_at"`
	Commits          map[string]string `json:"commits"`
	Reveals          map[string]string `json:"reveals"`
	Defaulted        []string          `json:"defaulted"`
	Seed             string            `json:"seed"`
	Reviewer         string            `json:"reviewer"`
	SelectionVersion string            `json:"selection_version"`
	Analysis         *Analysis         `json:"analysis"`
	Failure          *Failure          `json:"failure"`
	Audits           []Audit           `json:"audits"`
	Disputed         bool              `json:"disputed"`
	TxIDs            map[string]string `json:"tx_ids"`
}

// Event is an append-only ledger entry, keyed by transaction timestamp and ID.
type Event struct {
	TxID         string         `json:"tx_id"`
	EventType    string         `json:"event_type"`
	RecordedAt   string         `json:"recorded_at"`
	MSPID        string         `json:"msp_id"`
	Organization string         `json:"organization"`
	CodeHash     string         `json:"code_hash"`
	Payload      map[string]any `json:"payload"`
}

// TrainingStart records that the researcher started an approved algorithm.
type TrainingStart struct {
	RunID         string   `json:"run_id"`
	AlgorithmID   string   `json:"algorithm_id"`
	Organizations []string `json:"organizations"`
	ResearcherOrg string   `json:"researcher_org"`
	TxID          string   `json:"tx_id"`
	RecordedAt    string   `json:"recorded_at"`
}

// Context is everything the rules need from a transaction. The chaincode
// adapter implements it with the Fabric shim; tests use an in-memory version.
type Context interface {
	GetState(key string) ([]byte, error)
	PutState(key string, value []byte) error
	// Range returns values whose keys start with prefix, in key order.
	Range(prefix string) ([][]byte, error)
	MSPID() (string, error)
	Attribute(name string) (string, bool, error)
	IsAdmin() (bool, error)
	ClientID() (string, error)
	TxID() string
	Timestamp() (time.Time, error)
	// LocalConfig is the configuration this organization's chaincode container
	// was started with; InitConfig only accepts an identical value.
	LocalConfig() (*Config, error)
}
