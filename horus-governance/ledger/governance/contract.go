package governance

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

// Error carries a stable kind prefix ("invalid", "forbidden", "conflict",
// "notfound", "unavailable") so clients can map chaincode errors to HTTP.
type Error struct {
	Kind    string
	Message string
}

func (e *Error) Error() string { return e.Kind + ": " + e.Message }

func fail(kind, format string, values ...any) error {
	return &Error{Kind: kind, Message: fmt.Sprintf(format, values...)}
}

var (
	hexHash     = regexp.MustCompile(`^[0-9a-f]{64}$`)
	imageDigest = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)
	failureCode = regexp.MustCompile(`^[a-z][a-z_]{2,39}$`)
	runID       = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)
	submittedID = regexp.MustCompile(`^submitted-([0-9a-f]{64})$`)
	severities  = []string{"high", "medium", "low"}
)

// Invoke routes one transaction to its rule. It is the single entry point used
// by the chaincode adapter, so every function is listed here.
func Invoke(ctx Context, function string, args []string) ([]byte, error) {
	tx := &transaction{ctx: ctx}
	handlers := map[string]struct {
		arity int
		run   func([]string) (any, error)
	}{
		"InitConfig":            {1, func(a []string) (any, error) { return tx.initConfig(a[0]) }},
		"GetConfig":             {0, func([]string) (any, error) { return tx.config() }},
		"SubmitCode":            {2, func(a []string) (any, error) { return tx.submitCode(a[0], a[1]) }},
		"CommitSeed":            {2, func(a []string) (any, error) { return tx.commitSeed(a[0], a[1]) }},
		"RevealSeed":            {2, func(a []string) (any, error) { return tx.revealSeed(a[0], a[1]) }},
		"ForceDraw":             {1, func(a []string) (any, error) { return tx.forceDraw(a[0]) }},
		"RecordAnalysis":        {4, func(a []string) (any, error) { return tx.recordAnalysis(a[0], a[1], a[2], a[3]) }},
		"RecordAnalysisFailure": {2, func(a []string) (any, error) { return tx.recordFailure(a[0], a[1]) }},
		"AuditAnalysis":         {3, func(a []string) (any, error) { return tx.audit(a[0], a[1], a[2]) }},
		"RecordTrainingStart":   {3, func(a []string) (any, error) { return tx.recordTraining(a[0], a[1], a[2]) }},
		"GetSubmission":         {1, func(a []string) (any, error) { return tx.submission(a[0]) }},
		"GetCode":               {1, func(a []string) (any, error) { return tx.code(a[0]) }},
		"ListSubmissions":       {0, func([]string) (any, error) { return tx.listSubmissions() }},
		"ListEvents":            {0, func([]string) (any, error) { return tx.listEvents() }},
		"IsApproved":            {1, func(a []string) (any, error) { return tx.isApproved(a[0]) }},
	}
	handler, ok := handlers[function]
	if !ok {
		return nil, fail("invalid", "unknown function %q", function)
	}
	if len(args) != handler.arity {
		return nil, fail("invalid", "%s expects %d arguments", function, handler.arity)
	}
	result, err := handler.run(args)
	if err != nil {
		return nil, err
	}
	if raw, ok := result.([]byte); ok {
		return raw, nil
	}
	return json.Marshal(result)
}

type transaction struct {
	ctx    Context
	events int
}

type caller struct {
	MSPID        string
	Organization string
	Role         string
}

func sha256Hex(value []byte) string {
	sum := sha256.Sum256(value)
	return hex.EncodeToString(sum[:])
}

func (t *transaction) now() (string, time.Time, error) {
	stamp, err := t.ctx.Timestamp()
	if err != nil {
		return "", time.Time{}, fail("unavailable", "transaction timestamp unavailable")
	}
	stamp = stamp.UTC()
	return stamp.Format(timeLayout), stamp, nil
}

func (t *transaction) config() (*Config, error) {
	raw, err := t.ctx.GetState("config")
	if err != nil {
		return nil, fail("unavailable", "ledger state unavailable")
	}
	if raw == nil {
		return nil, fail("unavailable", "governance configuration has not been initialized")
	}
	var config Config
	if err := json.Unmarshal(raw, &config); err != nil {
		return nil, fail("unavailable", "stored configuration is invalid")
	}
	return &config, nil
}

func validateConfig(config *Config) error {
	if config.Version != 1 || config.Channel == "" || len(config.Organizations) < 2 ||
		!hexHash.MatchString(config.RulesHash) || !hexHash.MatchString(config.PolicyHash) ||
		config.SemgrepVersion == "" || config.RevealTimeoutSeconds < 30 || len(config.Rules) == 0 {
		return fail("invalid", "configuration is incomplete")
	}
	msps := map[string]bool{}
	for organization, msp := range config.Organizations {
		if organization == "" || msp == "" || msps[msp] || !imageDigest.MatchString(config.AnalyzerImages[organization]) {
			return fail("invalid", "every organization needs a unique MSP and an analyzer image digest")
		}
		msps[msp] = true
	}
	if len(config.AnalyzerImages) != len(config.Organizations) {
		return fail("invalid", "analyzer images must match organizations exactly")
	}
	for _, severity := range severities {
		if _, ok := config.Policy.Deductions[severity]; !ok {
			return fail("invalid", "policy deductions are incomplete")
		}
	}
	for id, rule := range config.Rules {
		if id == "" || rule.Message == "" || !contains(severities, rule.Severity) {
			return fail("invalid", "rule %q is incomplete", id)
		}
	}
	return nil
}

// initConfig stores the agreed configuration once. Because every endorsing
// chaincode container compares the argument with its own local file, a
// majority of organizations must hold the same configuration for it to pass.
func (t *transaction) initConfig(raw string) (any, error) {
	if admin, err := t.ctx.IsAdmin(); err != nil || !admin {
		return nil, fail("forbidden", "only an organization administrator can initialize the configuration")
	}
	var proposed Config
	decoder := json.NewDecoder(strings.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&proposed); err != nil {
		return nil, fail("invalid", "configuration is not valid JSON")
	}
	if err := validateConfig(&proposed); err != nil {
		return nil, err
	}
	local, err := t.ctx.LocalConfig()
	if err != nil {
		return nil, fail("unavailable", "local configuration of this organization is unavailable")
	}
	proposedBytes, _ := json.Marshal(proposed)
	localBytes, _ := json.Marshal(local)
	if !bytes.Equal(proposedBytes, localBytes) {
		return nil, fail("forbidden", "configuration differs from the one this organization agreed to")
	}
	existing, err := t.ctx.GetState("config")
	if err != nil {
		return nil, fail("unavailable", "ledger state unavailable")
	}
	if existing != nil {
		if !bytes.Equal(existing, proposedBytes) {
			return nil, fail("conflict", "a different configuration is already active")
		}
		return proposed, nil
	}
	if err := t.ctx.PutState("config", proposedBytes); err != nil {
		return nil, fail("unavailable", "configuration could not be stored")
	}
	who, err := t.identity(&proposed, "")
	if err != nil {
		who = caller{}
	}
	if err := t.event(who, "ConfigInitialized", "", map[string]any{
		"config_hash": sha256Hex(proposedBytes), "rules_hash": proposed.RulesHash,
		"policy_hash": proposed.PolicyHash, "semgrep_version": proposed.SemgrepVersion,
		"analyzer_images": proposed.AnalyzerImages}); err != nil {
		return nil, err
	}
	return proposed, nil
}

// identity resolves the caller's organization from its MSP and, when a role
// is required, checks the horus.role certificate attribute issued by the CA.
func (t *transaction) identity(config *Config, role string) (caller, error) {
	msp, err := t.ctx.MSPID()
	if err != nil {
		return caller{}, fail("forbidden", "caller identity unavailable")
	}
	organization := ""
	for name, candidate := range config.Organizations {
		if candidate == msp {
			organization = name
		}
	}
	if organization == "" {
		return caller{}, fail("forbidden", "caller does not belong to a member organization")
	}
	value, _, err := t.ctx.Attribute(RoleAttribute)
	if err != nil {
		return caller{}, fail("forbidden", "caller attributes unavailable")
	}
	if role != "" && value != role {
		return caller{}, fail("forbidden", "this function requires the %s role", role)
	}
	return caller{MSPID: msp, Organization: organization, Role: value}, nil
}

func (t *transaction) event(who caller, eventType, codeHash string, payload map[string]any) error {
	stamp, _, err := t.now()
	if err != nil {
		return err
	}
	t.events++
	value, _ := json.Marshal(Event{TxID: t.ctx.TxID(), EventType: eventType, RecordedAt: stamp,
		MSPID: who.MSPID, Organization: who.Organization, CodeHash: codeHash, Payload: payload})
	key := fmt.Sprintf("evt:%s:%s:%02d", stamp, t.ctx.TxID(), t.events)
	if err := t.ctx.PutState(key, value); err != nil {
		return fail("unavailable", "event could not be stored")
	}
	return nil
}

func (t *transaction) load(codeHash string) (*Submission, error) {
	if !hexHash.MatchString(codeHash) {
		return nil, fail("invalid", "a lowercase SHA-256 code hash is required")
	}
	raw, err := t.ctx.GetState("sub:" + codeHash)
	if err != nil {
		return nil, fail("unavailable", "ledger state unavailable")
	}
	if raw == nil {
		return nil, fail("notfound", "submission not found")
	}
	var submission Submission
	if err := json.Unmarshal(raw, &submission); err != nil {
		return nil, fail("unavailable", "stored submission is invalid")
	}
	return &submission, nil
}

func (t *transaction) save(submission *Submission) error {
	value, _ := json.Marshal(submission)
	if err := t.ctx.PutState("sub:"+submission.CodeHash, value); err != nil {
		return fail("unavailable", "submission could not be stored")
	}
	return nil
}

func contains(values []string, value string) bool {
	for _, candidate := range values {
		if candidate == value {
			return true
		}
	}
	return false
}

// validateCode mirrors sast/contracts.normalize_code: the API normalizes line
// endings first, so a carriage return here means the hash is not canonical.
func validateCode(code string) error {
	if len(code) == 0 || len(code) > MaxCodeBytes {
		return fail("invalid", "code must contain between 1 byte and %d bytes", MaxCodeBytes)
	}
	if !utf8.ValidString(code) {
		return fail("invalid", "code must be valid UTF-8")
	}
	blank := true
	for _, character := range code {
		if (character < 32 && character != '\t' && character != '\n') || (character >= 127 && character <= 159) {
			return fail("invalid", "binary content, control characters and carriage returns are not accepted")
		}
		if !unicode.IsSpace(character) {
			blank = false
		}
	}
	if blank {
		return fail("invalid", "code must not be empty")
	}
	return nil
}

// submitCode is called by the researcher identity. The researcher's
// organization comes from the certificate, never from a request field.
func (t *transaction) submitCode(code, selectedJSON string) (any, error) {
	config, err := t.config()
	if err != nil {
		return nil, err
	}
	who, err := t.identity(config, RoleResearcher)
	if err != nil {
		return nil, err
	}
	if err := validateCode(code); err != nil {
		return nil, err
	}
	var selected []string
	if err := json.Unmarshal([]byte(selectedJSON), &selected); err != nil || len(selected) == 0 {
		return nil, fail("invalid", "select at least one organization")
	}
	seen := map[string]bool{}
	var eligible []string
	for _, organization := range selected {
		if _, known := config.Organizations[organization]; !known || seen[organization] {
			return nil, fail("invalid", "select distinct known organizations")
		}
		seen[organization] = true
		if organization != who.Organization {
			eligible = append(eligible, organization)
		}
	}
	if len(eligible) == 0 {
		return nil, fail("invalid", "select at least one reviewer outside the researcher's organization")
	}
	sort.Strings(selected)
	sort.Strings(eligible)
	codeHash := sha256Hex([]byte(code))
	if existing, err := t.ctx.GetState("sub:" + codeHash); err != nil {
		return nil, fail("unavailable", "ledger state unavailable")
	} else if existing != nil {
		return nil, fail("conflict", "this code hash was already submitted")
	}
	clientID, err := t.ctx.ClientID()
	if err != nil {
		return nil, fail("forbidden", "caller identity unavailable")
	}
	stamp, _, err := t.now()
	if err != nil {
		return nil, err
	}
	submission := &Submission{
		CodeHash: codeHash, CodeBytes: len(code), Status: StatusDrawing, ResearcherOrg: who.Organization,
		ResearcherID: sha256Hex([]byte(clientID))[:32], Selected: selected, Eligible: eligible,
		CreatedAt: stamp, Commits: map[string]string{}, Reveals: map[string]string{},
		Defaulted: []string{}, Audits: []Audit{}, TxIDs: map[string]string{"CodeSubmitted": t.ctx.TxID()},
	}
	if err := t.ctx.PutState("code:"+codeHash, []byte(code)); err != nil {
		return nil, fail("unavailable", "code could not be stored")
	}
	if err := t.event(who, "CodeSubmitted", codeHash, map[string]any{
		"code_hash": codeHash, "researcher_org": who.Organization, "researcher_id": submission.ResearcherID,
		"selected": selected, "eligible": eligible}); err != nil {
		return nil, err
	}
	if len(eligible) == 1 {
		submission.Reviewer, submission.Status, submission.SelectionVersion = eligible[0], StatusAssigned, SelectionSingle
		if err := t.selected(who, submission); err != nil {
			return nil, err
		}
	}
	return submission, t.save(submission)
}

func (t *transaction) selected(who caller, submission *Submission) error {
	submission.TxIDs["ReviewerSelected"] = t.ctx.TxID()
	return t.event(who, "ReviewerSelected", submission.CodeHash, map[string]any{
		"code_hash": submission.CodeHash, "reviewer": submission.Reviewer, "eligible": submission.Eligible,
		"excluded": submission.ResearcherOrg, "defaulted": submission.Defaulted, "seed": submission.Seed,
		"selection_version": submission.SelectionVersion})
}

func (t *transaction) eligibleAgent(codeHash string) (*Config, caller, *Submission, error) {
	config, err := t.config()
	if err != nil {
		return nil, caller{}, nil, err
	}
	who, err := t.identity(config, RoleAgent)
	if err != nil {
		return nil, caller{}, nil, err
	}
	submission, err := t.load(codeHash)
	if err != nil {
		return nil, caller{}, nil, err
	}
	if !contains(submission.Eligible, who.Organization) {
		return nil, caller{}, nil, fail("forbidden", "%s is not eligible to review this submission", who.Organization)
	}
	return config, who, submission, nil
}

// commitSeed stores H(secret) for one eligible organization. Nobody can see the
// secret yet, so no organization can predict the draw while committing.
func (t *transaction) commitSeed(codeHash, commitment string) (any, error) {
	_, who, submission, err := t.eligibleAgent(codeHash)
	if err != nil {
		return nil, err
	}
	if submission.Status != StatusDrawing {
		return nil, fail("conflict", "the draw for this submission is closed")
	}
	if !hexHash.MatchString(commitment) {
		return nil, fail("invalid", "commitment must be a lowercase SHA-256 hex value")
	}
	if _, done := submission.Commits[who.Organization]; done {
		return nil, fail("conflict", "%s already committed", who.Organization)
	}
	if len(submission.Reveals) > 0 {
		return nil, fail("conflict", "reveals already started; late commits are not accepted")
	}
	submission.Commits[who.Organization] = commitment
	submission.TxIDs["SeedCommitted:"+who.Organization] = t.ctx.TxID()
	if err := t.event(who, "SeedCommitted", codeHash, map[string]any{
		"code_hash": codeHash, "organization": who.Organization, "commitment": commitment}); err != nil {
		return nil, err
	}
	return submission, t.save(submission)
}

func (t *transaction) expired(config *Config, submission *Submission) (bool, error) {
	_, now, err := t.now()
	if err != nil {
		return false, err
	}
	created, err := time.Parse(timeLayout, submission.CreatedAt)
	if err != nil {
		return false, fail("unavailable", "stored submission time is invalid")
	}
	return now.Sub(created) >= time.Duration(config.RevealTimeoutSeconds)*time.Second, nil
}

// revealSeed opens a commitment. Reveals start only after every eligible
// organization committed (or after the timeout, for those that did commit).
// The last reveal performs the draw inside the same transaction.
func (t *transaction) revealSeed(codeHash, secret string) (any, error) {
	config, who, submission, err := t.eligibleAgent(codeHash)
	if err != nil {
		return nil, err
	}
	if submission.Status != StatusDrawing {
		return nil, fail("conflict", "the draw for this submission is closed")
	}
	commitment, committed := submission.Commits[who.Organization]
	if !committed {
		return nil, fail("conflict", "%s has no commitment to reveal", who.Organization)
	}
	if _, done := submission.Reveals[who.Organization]; done {
		return nil, fail("conflict", "%s already revealed", who.Organization)
	}
	if len(submission.Commits) < len(submission.Eligible) {
		expired, err := t.expired(config, submission)
		if err != nil {
			return nil, err
		}
		if !expired {
			return nil, fail("conflict", "waiting for every eligible organization to commit")
		}
	}
	raw, err := hex.DecodeString(secret)
	if err != nil || len(raw) != 32 || sha256Hex(raw) != commitment {
		return nil, fail("invalid", "secret does not open the recorded commitment")
	}
	submission.Reveals[who.Organization] = secret
	submission.TxIDs["SeedRevealed:"+who.Organization] = t.ctx.TxID()
	if err := t.event(who, "SeedRevealed", codeHash, map[string]any{
		"code_hash": codeHash, "organization": who.Organization, "secret": secret}); err != nil {
		return nil, err
	}
	if len(submission.Reveals) == len(submission.Eligible) {
		draw(submission, submission.Eligible, SelectionCommitReveal)
		if err := t.selected(who, submission); err != nil {
			return nil, err
		}
	}
	return submission, t.save(submission)
}

// draw combines all revealed secrets; nobody chose the seed alone. The rank
// function is the same sha256-rank used before, so the result is recomputable.
func draw(submission *Submission, candidates []string, version string) {
	revealed := make([]string, 0, len(submission.Reveals))
	for organization := range submission.Reveals {
		revealed = append(revealed, organization)
	}
	sort.Strings(revealed)
	material, _ := hex.DecodeString(submission.CodeHash)
	for _, organization := range revealed {
		secret, _ := hex.DecodeString(submission.Reveals[organization])
		material = append(material, secret...)
	}
	seed := sha256.Sum256(material)
	ordered := append([]string(nil), candidates...)
	sort.Strings(ordered)
	reviewer, best := "", ""
	for _, organization := range ordered {
		rank := sha256Hex(append(seed[:], []byte(organization)...))
		if reviewer == "" || rank < best {
			reviewer, best = organization, rank
		}
	}
	submission.Seed = hex.EncodeToString(seed[:])
	submission.Reviewer = reviewer
	submission.SelectionVersion = version
	submission.Status = StatusAssigned
}

// forceDraw closes a stalled draw after the timeout. Organizations that did
// not reveal are publicly marked as defaulted and cannot become the reviewer.
func (t *transaction) forceDraw(codeHash string) (any, error) {
	config, who, submission, err := t.eligibleAgent(codeHash)
	if err != nil {
		return nil, err
	}
	if submission.Status != StatusDrawing {
		return nil, fail("conflict", "the draw for this submission is closed")
	}
	if _, revealed := submission.Reveals[who.Organization]; !revealed {
		return nil, fail("forbidden", "only an organization that revealed may close the draw")
	}
	expired, err := t.expired(config, submission)
	if err != nil {
		return nil, err
	}
	if !expired {
		return nil, fail("conflict", "the reveal timeout has not passed")
	}
	var candidates []string
	submission.Defaulted = []string{}
	for _, organization := range submission.Eligible {
		if _, revealed := submission.Reveals[organization]; revealed {
			candidates = append(candidates, organization)
		} else {
			submission.Defaulted = append(submission.Defaulted, organization)
		}
	}
	draw(submission, candidates, SelectionTimeout)
	if err := t.event(who, "DrawForced", codeHash, map[string]any{
		"code_hash": codeHash, "defaulted": submission.Defaulted}); err != nil {
		return nil, err
	}
	if err := t.selected(who, submission); err != nil {
		return nil, err
	}
	return submission, t.save(submission)
}

type reportFinding struct {
	RuleID   string `json:"rule_id"`
	Line     int    `json:"line"`
	Column   int    `json:"column"`
	Severity string `json:"severity"`
	Message  string `json:"message"`
}

type report struct {
	SchemaVersion  int             `json:"schema_version"`
	CodeHash       string          `json:"code_hash"`
	RulesHash      string          `json:"rules_hash"`
	PolicyHash     string          `json:"policy_hash"`
	SemgrepVersion string          `json:"semgrep_version"`
	Score          int             `json:"score"`
	Counts         map[string]int  `json:"counts"`
	Findings       []reportFinding `json:"findings"`
	Decision       string          `json:"decision"`
	Reasons        []string        `json:"reasons"`
}

// checkReport recomputes counts, score, decision and reasons exactly as
// sast/contracts.build_report does. A reviewer therefore cannot flip a
// decision without also hiding findings, which an audit re-execution exposes.
func checkReport(config *Config, codeHash, reportJSON, reportHash string) (*report, error) {
	if !hexHash.MatchString(reportHash) || sha256Hex([]byte(reportJSON)) != reportHash {
		return nil, fail("invalid", "report hash does not match the report bytes")
	}
	var parsed report
	decoder := json.NewDecoder(strings.NewReader(reportJSON))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&parsed); err != nil {
		return nil, fail("invalid", "report is not a valid Horus report")
	}
	if parsed.SchemaVersion != 1 || parsed.CodeHash != codeHash || parsed.RulesHash != config.RulesHash ||
		parsed.PolicyHash != config.PolicyHash || parsed.SemgrepVersion != config.SemgrepVersion {
		return nil, fail("invalid", "report was not produced for this code with the agreed rules, policy and engine")
	}
	counts := map[string]int{"high": 0, "medium": 0, "low": 0}
	for _, finding := range parsed.Findings {
		rule, known := config.Rules[finding.RuleID]
		if !known || rule.Severity != finding.Severity || rule.Message != finding.Message ||
			finding.Line < 1 || finding.Column < 1 {
			return nil, fail("invalid", "report contains a finding outside the agreed rule set")
		}
		counts[finding.Severity]++
	}
	score := 100
	for _, severity := range severities {
		score -= counts[severity] * config.Policy.Deductions[severity]
	}
	if score < 0 {
		score = 0
	}
	var reasons []string
	if counts["high"] > config.Policy.MaximumHighFindings {
		reasons = append(reasons, "High-severity findings are not permitted.")
	}
	if score < config.Policy.MinimumScore {
		reasons = append(reasons, "Security score is below the required minimum.")
	}
	decision := StatusRejected
	if len(reasons) == 0 {
		decision = StatusApproved
		reasons = []string{"No high-severity findings and security score meets policy."}
	}
	if len(parsed.Counts) != 3 || parsed.Counts["high"] != counts["high"] || parsed.Counts["medium"] != counts["medium"] ||
		parsed.Counts["low"] != counts["low"] || parsed.Score != score || parsed.Decision != decision ||
		strings.Join(parsed.Reasons, "\n") != strings.Join(reasons, "\n") {
		return nil, fail("invalid", "report score or decision is inconsistent with its findings and the agreed policy")
	}
	return &parsed, nil
}

func (t *transaction) recordAnalysis(codeHash, reportJSON, reportHash, digest string) (any, error) {
	config, who, submission, err := t.eligibleAgent(codeHash)
	if err != nil {
		return nil, err
	}
	if submission.Reviewer != who.Organization {
		return nil, fail("forbidden", "only the drawn reviewer %s may record the analysis", submission.Reviewer)
	}
	if submission.Status != StatusAssigned && submission.Status != StatusError {
		return nil, fail("conflict", "this submission already has a recorded analysis")
	}
	if digest != config.AnalyzerImages[who.Organization] {
		return nil, fail("invalid", "analysis did not run on the agreed analyzer image")
	}
	parsed, err := checkReport(config, codeHash, reportJSON, reportHash)
	if err != nil {
		return nil, err
	}
	stamp, _, err := t.now()
	if err != nil {
		return nil, err
	}
	submission.Analysis = &Analysis{Organization: who.Organization, MSPID: who.MSPID, ReportJSON: reportJSON,
		ReportHash: reportHash, Decision: parsed.Decision, Score: parsed.Score, ImageDigest: digest,
		TxID: t.ctx.TxID(), RecordedAt: stamp}
	submission.Failure = nil
	submission.Status = parsed.Decision
	submission.TxIDs["CodeAnalyzed"] = t.ctx.TxID()
	if err := t.event(who, "CodeAnalyzed", codeHash, map[string]any{
		"code_hash": codeHash, "reviewer": who.Organization, "report_hash": reportHash, "score": parsed.Score,
		"counts": parsed.Counts, "decision": parsed.Decision, "image_digest": digest,
		"rules_hash": parsed.RulesHash, "policy_hash": parsed.PolicyHash,
		"semgrep_version": parsed.SemgrepVersion}); err != nil {
		return nil, err
	}
	outcome := "CodeRejected"
	if parsed.Decision == StatusApproved {
		outcome = "CodeValidated"
	}
	if err := t.event(who, outcome, codeHash, map[string]any{
		"code_hash": codeHash, "report_hash": reportHash, "decision": parsed.Decision}); err != nil {
		return nil, err
	}
	if parsed.Decision == StatusApproved {
		if err := t.event(who, "AlgorithmRegistered", codeHash, map[string]any{
			"algorithm_id": "submitted-" + codeHash, "code_hash": codeHash, "report_hash": reportHash,
			"score": parsed.Score, "validation_source": "semgrep", "executable": false}); err != nil {
			return nil, err
		}
	}
	return submission, t.save(submission)
}

func (t *transaction) recordFailure(codeHash, code string) (any, error) {
	_, who, submission, err := t.eligibleAgent(codeHash)
	if err != nil {
		return nil, err
	}
	if submission.Reviewer != who.Organization || submission.Status != StatusAssigned {
		return nil, fail("forbidden", "only the drawn reviewer may report a failure while the analysis is pending")
	}
	if !failureCode.MatchString(code) {
		return nil, fail("invalid", "failure code must be a short lowercase identifier")
	}
	stamp, _, err := t.now()
	if err != nil {
		return nil, err
	}
	submission.Failure = &Failure{Organization: who.Organization, Code: code, TxID: t.ctx.TxID(), RecordedAt: stamp}
	submission.Status = StatusError
	submission.TxIDs["AnalysisFailed"] = t.ctx.TxID()
	if err := t.event(who, "AnalysisFailed", codeHash, map[string]any{
		"code_hash": codeHash, "reviewer": who.Organization, "code": code}); err != nil {
		return nil, err
	}
	return submission, t.save(submission)
}

// audit lets another eligible organization re-run the deterministic analysis.
// A different report hash marks the submission as disputed for everyone.
func (t *transaction) audit(codeHash, reportHash, digest string) (any, error) {
	config, who, submission, err := t.eligibleAgent(codeHash)
	if err != nil {
		return nil, err
	}
	if submission.Analysis == nil {
		return nil, fail("conflict", "there is no analysis to audit yet")
	}
	if who.Organization == submission.Reviewer {
		return nil, fail("forbidden", "the reviewer cannot audit its own analysis")
	}
	for _, existing := range submission.Audits {
		if existing.Organization == who.Organization {
			return nil, fail("conflict", "%s already audited this analysis", who.Organization)
		}
	}
	if !hexHash.MatchString(reportHash) {
		return nil, fail("invalid", "a lowercase SHA-256 report hash is required")
	}
	if digest != config.AnalyzerImages[who.Organization] {
		return nil, fail("invalid", "audit did not run on the agreed analyzer image")
	}
	stamp, _, err := t.now()
	if err != nil {
		return nil, err
	}
	match := reportHash == submission.Analysis.ReportHash
	submission.Audits = append(submission.Audits, Audit{Organization: who.Organization, ReportHash: reportHash,
		ImageDigest: digest, Match: match, TxID: t.ctx.TxID(), RecordedAt: stamp})
	if !match {
		submission.Disputed = true
	}
	submission.TxIDs["AnalysisAudited:"+who.Organization] = t.ctx.TxID()
	if err := t.event(who, "AnalysisAudited", codeHash, map[string]any{
		"code_hash": codeHash, "auditor": who.Organization, "report_hash": reportHash,
		"expected_report_hash": submission.Analysis.ReportHash, "match": match}); err != nil {
		return nil, err
	}
	return submission, t.save(submission)
}

func (t *transaction) recordTraining(id, algorithm, organizationsJSON string) (any, error) {
	config, err := t.config()
	if err != nil {
		return nil, err
	}
	who, err := t.identity(config, RoleResearcher)
	if err != nil {
		return nil, err
	}
	if !runID.MatchString(id) {
		return nil, fail("invalid", "run ID must be a lowercase UUID")
	}
	var organizations []string
	if err := json.Unmarshal([]byte(organizationsJSON), &organizations); err != nil || len(organizations) < 2 {
		return nil, fail("invalid", "at least two organizations are required")
	}
	seen := map[string]bool{}
	for _, organization := range organizations {
		if _, known := config.Organizations[organization]; !known || seen[organization] {
			return nil, fail("invalid", "organizations must be distinct members")
		}
		seen[organization] = true
	}
	if algorithm != Builtin {
		match := submittedID.FindStringSubmatch(algorithm)
		if match == nil {
			return nil, fail("invalid", "unknown algorithm")
		}
		approval, err := t.isApproved(match[1])
		if err != nil {
			return nil, err
		}
		if !approval["approved"].(bool) {
			return nil, fail("forbidden", "algorithm is not approved on the ledger")
		}
	}
	stamp, _, err := t.now()
	if err != nil {
		return nil, err
	}
	record := TrainingStart{RunID: id, AlgorithmID: algorithm, Organizations: organizations,
		ResearcherOrg: who.Organization, TxID: t.ctx.TxID(), RecordedAt: stamp}
	existing, err := t.ctx.GetState("train:" + id)
	if err != nil {
		return nil, fail("unavailable", "ledger state unavailable")
	}
	if existing != nil {
		var previous TrainingStart
		if json.Unmarshal(existing, &previous) == nil && previous.AlgorithmID == algorithm &&
			strings.Join(previous.Organizations, ",") == strings.Join(organizations, ",") {
			return previous, nil
		}
		return nil, fail("conflict", "this run ID was recorded with different parameters")
	}
	value, _ := json.Marshal(record)
	if err := t.ctx.PutState("train:"+id, value); err != nil {
		return nil, fail("unavailable", "training record could not be stored")
	}
	if err := t.event(who, "TrainingStarted", "", map[string]any{
		"run_id": id, "algorithm_id": algorithm, "organizations": organizations,
		"researcher_org": who.Organization}); err != nil {
		return nil, err
	}
	return record, nil
}

func (t *transaction) submission(codeHash string) (any, error) {
	return t.load(codeHash)
}

func (t *transaction) code(codeHash string) (any, error) {
	config, err := t.config()
	if err != nil {
		return nil, err
	}
	if _, err := t.identity(config, ""); err != nil {
		return nil, err
	}
	if !hexHash.MatchString(codeHash) {
		return nil, fail("invalid", "a lowercase SHA-256 code hash is required")
	}
	raw, err := t.ctx.GetState("code:" + codeHash)
	if err != nil {
		return nil, fail("unavailable", "ledger state unavailable")
	}
	if raw == nil {
		return nil, fail("notfound", "code not found")
	}
	return raw, nil
}

func (t *transaction) listSubmissions() (any, error) {
	values, err := t.ctx.Range("sub:")
	if err != nil {
		return nil, fail("unavailable", "ledger state unavailable")
	}
	submissions := make([]Submission, 0, len(values))
	for _, value := range values {
		var submission Submission
		if json.Unmarshal(value, &submission) == nil {
			submissions = append(submissions, submission)
		}
	}
	sort.Slice(submissions, func(i, j int) bool { return submissions[i].CreatedAt > submissions[j].CreatedAt })
	return submissions, nil
}

func (t *transaction) listEvents() (any, error) {
	values, err := t.ctx.Range("evt:")
	if err != nil {
		return nil, fail("unavailable", "ledger state unavailable")
	}
	events := make([]Event, 0, len(values))
	for _, value := range values {
		var event Event
		if json.Unmarshal(value, &event) == nil {
			events = append(events, event)
		}
	}
	return events, nil
}

func (t *transaction) isApproved(codeHash string) (map[string]any, error) {
	submission, err := t.load(codeHash)
	if err != nil {
		return nil, err
	}
	return map[string]any{"code_hash": codeHash, "status": submission.Status, "disputed": submission.Disputed,
		"approved": submission.Status == StatusApproved && !submission.Disputed}, nil
}
