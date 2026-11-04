package abac

import (
	"encoding/json"
	"slices"
	"strings"
)

// Policy is declarative JSON stored by the PAP and interpreted by the PDP, so
// a policy can change (UpdatePolicy) without redeploying the chaincode. Rules
// are combined with AND; the first failing rule gives the denial reason.
type Policy struct {
	PolicyID    string   `json:"policyId"`
	Version     int      `json:"version"`
	Description string   `json:"description,omitempty"`
	Actions     []string `json:"actions"`
	Rules       []Rule   `json:"rules"`
	PolicyHash  string   `json:"policyHash"`
	UpdatedBy   string   `json:"updatedBy"`
	UpdatedAt   string   `json:"updatedAt"`
	TxID        string   `json:"txId"`
}

// Rule types: subjectRole (value: role), subjectMsp (value: MSP ID),
// resourceLabel (value: security label) and consent (checks below).
type Rule struct {
	Type   string   `json:"type"`
	Value  string   `json:"value,omitempty"`
	Checks []string `json:"checks,omitempty"`
}

// Consent checks: exists is mandatory; grantee = the requester is the
// beneficiary; patient = consent patient equals the resource patient;
// active = not revoked; notExpired = validUntil after the transaction time.
var consentChecks = []string{"exists", "grantee", "patient", "active", "notExpired"}

type policyBody struct {
	Description string   `json:"description,omitempty"`
	Actions     []string `json:"actions"`
	Rules       []Rule   `json:"rules"`
}

func parsePolicy(policyID, raw string) (policyBody, error) {
	var body policyBody
	if err := checkID("policyId", policyID); err != nil {
		return body, err
	}
	decoder := json.NewDecoder(strings.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&body); err != nil {
		return body, fail("invalid", "policy JSON: %v", err)
	}
	if len(body.Description) > 200 {
		return body, fail("invalid", "description is limited to 200 characters")
	}
	if len(body.Actions) == 0 || len(body.Rules) == 0 {
		return body, fail("invalid", "a policy needs at least one action and one rule")
	}
	for _, action := range body.Actions {
		if !wordPattern.MatchString(action) {
			return body, fail("invalid", "action %q is not a simple word", action)
		}
	}
	for index, rule := range body.Rules {
		if err := validateRule(rule); err != nil {
			return body, fail("invalid", "rule %d: %s", index, err.(*Error).Message)
		}
	}
	return body, nil
}

func validateRule(rule Rule) error {
	switch rule.Type {
	case "subjectRole":
		if _, known := roleIssuer[rule.Value]; !known || len(rule.Checks) > 0 {
			return fail("invalid", "subjectRole needs a known role as value")
		}
	case "subjectMsp":
		if (rule.Value != HospitalMSP && rule.Value != LabMSP) || len(rule.Checks) > 0 {
			return fail("invalid", "subjectMsp needs %s or %s", HospitalMSP, LabMSP)
		}
	case "resourceLabel":
		if !labelPattern.MatchString(rule.Value) || len(rule.Checks) > 0 {
			return fail("invalid", "resourceLabel needs a label as value")
		}
	case "consent":
		if rule.Value != "" || !slices.Contains(rule.Checks, "exists") {
			return fail("invalid", "consent needs checks including \"exists\" and no value")
		}
		for _, check := range rule.Checks {
			if !slices.Contains(consentChecks, check) {
				return fail("invalid", "unknown consent check %q", check)
			}
		}
	default:
		return fail("invalid", "unknown rule type %q", rule.Type)
	}
	return nil
}

func policyHash(policyID string, version int, body policyBody) (string, error) {
	raw, err := Canonical(map[string]any{"policyId": policyID, "version": version,
		"description": body.Description, "actions": body.Actions, "rules": body.Rules})
	return sha256Hex(raw), err
}
