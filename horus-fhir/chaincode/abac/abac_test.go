package abac

import (
	"encoding/json"
	"strings"
	"testing"
	"time"
)

func expectDeny(t *testing.T, decision Decision, reason string) {
	t.Helper()
	if decision.Permitted || decision.Reason != reason {
		t.Fatalf("want deny %s, got permitted=%v reason=%s trace=%+v", reason, decision.Permitted, decision.Reason, decision.Trace)
	}
}

func TestPermitAnaExamA(t *testing.T) {
	w := scenario(t)
	decision := w.access(ana, "report-A")
	if !decision.Permitted || decision.Reason != ReasonPermit {
		t.Fatalf("want permit, got %+v", decision)
	}
	if decision.PolicyID != "ConsentRequiredPolicy" || decision.ReportHash != hash("report A") {
		t.Fatalf("decision must name the policy and carry the on-chain hash for the PEP: %+v", decision)
	}
	components := []string{}
	for _, step := range decision.Trace {
		components = append(components, step.Component)
	}
	if got := strings.Join(components, ","); !strings.Contains(got, "PIP,PAP") || !strings.HasSuffix(got, "PIP,PDP") {
		t.Fatalf("trace must show PDP -> PIP -> PAP -> ... -> PDP, got %s", got)
	}
	// The decision is recorded on the ledger and emitted as one event.
	var stored Decision
	if err := json.Unmarshal(w.must(ana, "PDP:GetDecision", decision.TxID), &stored); err != nil || !stored.Permitted {
		t.Fatalf("decision not recorded: %v %+v", err, stored)
	}
	last := w.events[len(w.events)-1]
	if last.Name != "AccessDecision" || last.Detail["permitted"] != "true" || last.Detail["requester"] != "phy-001" {
		t.Fatalf("unexpected event %+v", last)
	}
}

func TestDenyOtherExam(t *testing.T) {
	expectDeny(t, scenario(t).access(ana, "report-B"), ReasonNoConsent)
}

func TestDenyOtherPhysician(t *testing.T) {
	expectDeny(t, scenario(t).access(bruno, "report-A"), ReasonWrongGrantee)
}

func TestDenyExpired(t *testing.T) {
	w := scenario(t)
	w.clock = clock0.Add(30*24*time.Hour + time.Second) // transaction time, not the local clock
	expectDeny(t, w.access(ana, "report-A"), ReasonExpired)
}

func TestDenyRevoked(t *testing.T) {
	w := scenario(t)
	w.must(joao, "PIP:RevokeConsent", "consent-A")
	expectDeny(t, w.access(ana, "report-A"), ReasonRevoked)
}

func TestDenyResourceWithoutPolicy(t *testing.T) {
	w := scenario(t)
	w.must(lab, "PIP:PutResource", "report-C", "sr-A", "pat-001", hash("report C"), "N", "lab-001")
	expectDeny(t, w.access(ana, "report-C"), ReasonNoPolicy)
	expectDeny(t, w.access(ana, "report-unknown"), ReasonUnknownResource)
}

func TestOnlyThePatientWritesConsent(t *testing.T) {
	w := scenario(t)
	until := clock0.Add(time.Hour).Format(time.RFC3339)
	// A physician, the lab and the admin are not patients.
	for _, who := range []identity{ana, lab, admin} {
		w.refused(who, "forbidden", "PIP:PutConsent", "consent-X", "sr-B", "pat-001", who.id, until, hash("x"))
	}
	// Another patient cannot consent in João's name, nor revoke his consent.
	w.refused(maria, "forbidden", "PIP:PutConsent", "consent-X", "sr-B", "pat-001", "phy-001", until, hash("x"))
	w.refused(maria, "forbidden", "PIP:RevokeConsent", "consent-A")
}

func TestConsentOfAnotherPatientDoesNotCount(t *testing.T) {
	w := scenario(t)
	until := clock0.Add(time.Hour).Format(time.RFC3339)
	w.must(maria, "PIP:PutConsent", "consent-M", "sr-A", "pat-002", "phy-002", until, hash("m"))
	expectDeny(t, w.access(bruno, "report-A"), ReasonPatientMismatch)
}

func TestRolesArePinnedToTheirMSP(t *testing.T) {
	w := scenario(t)
	// The lab's CA can issue any attribute, but role=admin/physician only
	// counts when HospitalMSP issued it.
	fakeAdmin := identity{"lab-admin", LabMSP, RoleAdmin}
	w.refused(fakeAdmin, "forbidden", "PAP:CreatePolicy", "Open", `{"actions":["read"],"rules":[{"type":"subjectMsp","value":"LabMSP"}]}`)
	fakePhysician := identity{"phy-001", LabMSP, RolePhysician}
	expectDeny(t, w.access(fakePhysician, "report-A"), ReasonNotPhysician)
	expectDeny(t, w.access(lab, "report-A"), ReasonNotPhysician)
	w.refused(ana, "forbidden", "PAP:BindResource", "resource:report-A", "ConsentRequiredPolicy")
	w.refused(ana, "forbidden", "PIP:PutResource", "report-Z", "sr-A", "pat-001", hash("z"), "R", "phy-001")
}

func TestDeniesAreRecordedToo(t *testing.T) {
	w := scenario(t)
	decision := w.access(bruno, "report-A")
	var stored Decision
	if err := json.Unmarshal(w.must(admin, "PDP:GetDecision", decision.TxID), &stored); err != nil || stored.Reason != ReasonWrongGrantee {
		t.Fatalf("deny not recorded: %v %+v", err, stored)
	}
}

func TestLabelBindingAndPolicyUpdate(t *testing.T) {
	w := scenario(t)
	w.must(lab, "PIP:PutResource", "report-L", "sr-A", "pat-001", hash("report L"), "R", "lab-001")
	expectDeny(t, w.access(ana, "report-L"), ReasonNoPolicy)
	w.must(admin, "PAP:BindResource", "label:R", "ConsentRequiredPolicy")
	if decision := w.access(ana, "report-L"); !decision.Permitted {
		t.Fatalf("label binding should apply: %+v", decision)
	}
	// Changing the policy is data, not code: no redeploy of the PDP.
	w.must(admin, "PAP:UpdatePolicy", "ConsentRequiredPolicy", `{"actions":["read"],"rules":[{"type":"subjectRole","value":"patient"}]}`)
	decision := w.access(ana, "report-A")
	if decision.Permitted || decision.Reason != ReasonWrongRole || decision.PolicyVersion != 2 {
		t.Fatalf("updated policy not applied: %+v", decision)
	}
}

func TestValidation(t *testing.T) {
	w := scenario(t)
	w.refused(admin, "invalid", "PAP:CreatePolicy", "Bad", `{"actions":["read"],"rules":[{"type":"script","value":"x"}]}`)
	w.refused(admin, "invalid", "PAP:CreatePolicy", "Empty", `{"actions":["read"],"rules":[]}`)
	w.refused(admin, "conflict", "PAP:CreatePolicy", "ConsentRequiredPolicy", consentRequired)
	w.refused(lab, "conflict", "PIP:PutResource", "report-A", "sr-A", "pat-001", hash("other"), "R", "lab-001")
	w.refused(lab, "invalid", "PIP:PutResource", "report-Y", "sr-A", "pat-001", "not-a-hash", "R", "lab-001")
	w.refused(joao, "invalid", "PIP:PutConsent", "consent-Y", "sr-B", "pat-001", "phy-001", clock0.Add(-time.Hour).Format(time.RFC3339), hash("y"))
	w.refused(joao, "invalid", "PIP:PutConsent", "consent Y", "sr-B", "pat-001", "phy-001", clock0.Add(time.Hour).Format(time.RFC3339), hash("y"))
	w.refused(admin, "invalid", "PAP:Nope")
}

func TestEventsAndCanonicalJSON(t *testing.T) {
	w := scenario(t)
	w.access(ana, "report-A")
	var events []Event
	if err := json.Unmarshal(w.must(ana, "ListEvents"), &events); err != nil {
		t.Fatal(err)
	}
	names := []string{}
	for _, event := range events {
		names = append(names, event.Name)
	}
	if len(events) != 7 {
		t.Fatalf("want 7 events (6 writes + 1 decision), got %d: %v", len(events), names)
	}
	raw, _ := Canonical(map[string]any{"b": 1, "a": "<é>"})
	if string(raw) != `{"a":"<é>","b":1}` {
		t.Fatalf("canonical JSON: %s", raw)
	}
}
