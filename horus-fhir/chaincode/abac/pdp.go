package abac

import (
	"slices"
	"time"
)

// TraceStep records which component was asked what, and what it answered.
// Only IDs, hashes, labels, deadlines and statuses appear here.
type TraceStep struct {
	Component  string            `json:"component"`
	Action     string            `json:"action"`
	Result     string            `json:"result"`
	Attributes map[string]string `json:"attributes,omitempty"`
}

// Decision is stored under decision:<txId> and returned to the PEP.
type Decision struct {
	TxID          string      `json:"txId"`
	Requester     Subject     `json:"requester"`
	ReportID      string      `json:"reportId"`
	Action        string      `json:"action"`
	PolicyID      string      `json:"policyId,omitempty"`
	PolicyVersion int         `json:"policyVersion,omitempty"`
	PolicyHash    string      `json:"policyHash,omitempty"`
	Permitted     bool        `json:"permitted"`
	Reason        string      `json:"reason"`
	ReportHash    string      `json:"reportHash,omitempty"`
	DecidedAt     string      `json:"decidedAt"`
	Trace         []TraceStep `json:"trace"`
}

// PDP is the Policy Decision Point. It reads the PAP and the PIP only through
// their reader interfaces and writes nothing but its own decision.
type PDP struct {
	ctx Context
	pap PolicyReader
	pip AttributeReader
}

// RequestAccess evaluates, records the decision and emits AccessDecision. A
// denial is a successful transaction too, so it is committed to the ledger.
func (p PDP) RequestAccess(reportID, action string) (*Decision, error) {
	if err := checkID("reportId", reportID); err != nil {
		return nil, err
	}
	if !wordPattern.MatchString(action) {
		return nil, fail("invalid", "action must be a simple word")
	}
	who, err := subject(p.ctx)
	if err != nil {
		return nil, err
	}
	at, err := now(p.ctx)
	if err != nil {
		return nil, err
	}
	decision := &Decision{TxID: p.ctx.TxID(), Requester: who, ReportID: reportID, Action: action,
		DecidedAt: at.Format(timeLayout)}
	decision.Trace = append(decision.Trace, TraceStep{Component: "PDP", Action: "subject from certificate",
		Result: "ok", Attributes: map[string]string{"id": who.ID, "msp": who.MSP, "role": who.Role}})
	decision.Permitted, decision.Reason, err = p.evaluate(decision, who, reportID, action, at)
	if err != nil {
		return nil, err
	}
	if err := store(p.ctx, "decision:"+decision.TxID, decision); err != nil {
		return nil, err
	}
	return decision, emit(p.ctx, "PDP", "AccessDecision", who.ID, at, map[string]string{
		"requester": who.ID, "reportId": reportID, "policyId": decision.PolicyID,
		"permitted": map[bool]string{true: "true", false: "false"}[decision.Permitted], "reason": decision.Reason})
}

func (p PDP) evaluate(decision *Decision, who Subject, reportID, action string, at time.Time) (bool, string, error) {
	trace := func(component, step, result string, attributes map[string]string) {
		decision.Trace = append(decision.Trace, TraceStep{component, step, result, attributes})
	}
	resource, err := p.pip.Resource(reportID)
	if err != nil {
		return false, "", err
	}
	if resource == nil {
		trace("PIP", "resource attributes", "not registered", nil)
		return false, ReasonUnknownResource, nil
	}
	decision.ReportHash = resource.ReportHash
	trace("PIP", "resource attributes", "found", map[string]string{"reportId": resource.ReportID,
		"serviceRequestId": resource.ServiceRequestID, "patientPseudo": resource.PatientPseudo,
		"reportHash": resource.ReportHash, "securityLabel": resource.SecurityLabel, "labId": resource.LabID})

	policy, binding, err := p.pap.PolicyFor(reportID, resource.SecurityLabel)
	if err != nil {
		return false, "", err
	}
	if policy == nil {
		trace("PAP", "policy for resource", "none bound (deny by default)", nil)
		return false, ReasonNoPolicy, nil
	}
	decision.PolicyID, decision.PolicyVersion, decision.PolicyHash = policy.PolicyID, policy.Version, policy.PolicyHash
	trace("PAP", "policy for resource", policy.PolicyID, map[string]string{"boundBy": binding.Target,
		"version": itoa(policy.Version), "policyHash": policy.PolicyHash})

	if !slices.Contains(policy.Actions, action) {
		trace("PDP", "action", "not allowed by policy", map[string]string{"action": action})
		return false, ReasonActionNotAllowed, nil
	}
	for _, rule := range policy.Rules {
		ok, reason, err := p.rule(rule, who, resource, at, trace)
		if err != nil || !ok {
			return false, reason, err
		}
	}
	trace("PDP", "evaluate", "all rules satisfied", nil)
	return true, ReasonPermit, nil
}

func (p PDP) rule(rule Rule, who Subject, resource *Resource, at time.Time,
	trace func(string, string, string, map[string]string)) (bool, string, error) {
	switch rule.Type {
	case "subjectRole":
		if who.Role != rule.Value {
			trace("PDP", "rule subjectRole="+rule.Value, "failed", map[string]string{"role": who.Role})
			if rule.Value == RolePhysician {
				return false, ReasonNotPhysician, nil
			}
			return false, ReasonWrongRole, nil
		}
		trace("PDP", "rule subjectRole="+rule.Value, "ok", nil)
	case "subjectMsp":
		if who.MSP != rule.Value {
			trace("PDP", "rule subjectMsp="+rule.Value, "failed", map[string]string{"msp": who.MSP})
			return false, ReasonWrongOrganization, nil
		}
		trace("PDP", "rule subjectMsp="+rule.Value, "ok", nil)
	case "resourceLabel":
		if resource.SecurityLabel != rule.Value {
			trace("PDP", "rule resourceLabel="+rule.Value, "failed", nil)
			return false, ReasonLabelMismatch, nil
		}
		trace("PDP", "rule resourceLabel="+rule.Value, "ok", nil)
	case "consent":
		return p.consent(rule, who, resource, at, trace)
	default: // unreachable: the PAP validates rule types
		return false, ReasonNoPolicy, nil
	}
	return true, "", nil
}

// consent applies the policy's consent checks to the consents the PIP holds
// for the resource's ServiceRequest.
func (p PDP) consent(rule Rule, who Subject, resource *Resource, at time.Time,
	trace func(string, string, string, map[string]string)) (bool, string, error) {
	all, err := p.pip.ConsentsForRequest(resource.ServiceRequestID)
	if err != nil {
		return false, "", err
	}
	trace("PIP", "consents for serviceRequestId", itoa(len(all))+" found",
		map[string]string{"serviceRequestId": resource.ServiceRequestID})
	if len(all) == 0 {
		return false, ReasonNoConsent, nil
	}
	candidates := all
	if slices.Contains(rule.Checks, "grantee") {
		candidates = filter(candidates, func(c Consent) bool { return c.Grantee == who.ID })
		if len(candidates) == 0 {
			trace("PDP", "consent grantee", "requester is not a beneficiary", map[string]string{"requester": who.ID})
			return false, ReasonWrongGrantee, nil
		}
	}
	if slices.Contains(rule.Checks, "patient") {
		candidates = filter(candidates, func(c Consent) bool { return c.PatientPseudo == resource.PatientPseudo })
		if len(candidates) == 0 {
			trace("PDP", "consent patient", "consent is not from the resource's patient", nil)
			return false, ReasonPatientMismatch, nil
		}
	}
	reason := ""
	for _, consent := range candidates {
		attributes := map[string]string{"consentId": consent.ConsentID, "grantee": consent.Grantee,
			"patientPseudo": consent.PatientPseudo, "status": consent.Status, "validUntil": consent.ValidUntil,
			"consentHash": consent.ConsentHash}
		if slices.Contains(rule.Checks, "active") && consent.Status != ConsentActive {
			trace("PIP", "consent "+consent.ConsentID, "revoked", attributes)
			reason = firstOf(reason, ReasonRevoked)
			continue
		}
		until, err := time.Parse(timeLayout, consent.ValidUntil)
		if err != nil {
			return false, "", err
		}
		if slices.Contains(rule.Checks, "notExpired") && !at.Before(until) {
			trace("PIP", "consent "+consent.ConsentID, "expired", attributes)
			reason = firstOf(reason, ReasonExpired)
			continue
		}
		trace("PIP", "consent "+consent.ConsentID, "valid", attributes)
		return true, "", nil
	}
	return false, reason, nil
}

func filter(consents []Consent, keep func(Consent) bool) []Consent {
	kept := []Consent{}
	for _, consent := range consents {
		if keep(consent) {
			kept = append(kept, consent)
		}
	}
	return kept
}

func firstOf(current, candidate string) string {
	if current != "" {
		return current
	}
	return candidate
}

// GetDecision returns a recorded decision by transaction ID.
func (p PDP) GetDecision(txID string) (*Decision, error) {
	var decision Decision
	found, err := load(p.ctx, "decision:"+txID, &decision)
	if err != nil {
		return nil, err
	}
	if !found {
		return nil, fail("notfound", "no decision for transaction %s", txID)
	}
	return &decision, nil
}
