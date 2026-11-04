package abac

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"testing"
	"time"
)

// identity is what a certificate would say.
type identity struct{ id, msp, role string }

var (
	admin  = identity{"adm-001", HospitalMSP, RoleAdmin}
	joao   = identity{"pat-001", HospitalMSP, RolePatient}
	maria  = identity{"pat-002", HospitalMSP, RolePatient}
	ana    = identity{"phy-001", HospitalMSP, RolePhysician}
	bruno  = identity{"phy-002", HospitalMSP, RolePhysician}
	lab    = identity{"lab-001", LabMSP, RoleLab}
	clock0 = time.Date(2026, 11, 4, 12, 0, 0, 0, time.UTC)
)

// world mimics Fabric: a transaction reads committed state only, and its
// writes and event are committed only if the function returns no error.
type world struct {
	t      *testing.T
	state  map[string][]byte
	events []Event
	clock  time.Time
	txs    int
}

func newWorld(t *testing.T) *world {
	return &world{t: t, state: map[string][]byte{}, clock: clock0}
}

type tx struct {
	w      *world
	who    identity
	id     string
	writes map[string][]byte
	event  []byte
}

func (x *tx) GetState(key string) ([]byte, error) { return x.w.state[key], nil }
func (x *tx) PutState(key string, value []byte) error {
	x.writes[key] = append([]byte(nil), value...)
	return nil
}
func (x *tx) Range(prefix string) ([][]byte, error) {
	keys := []string{}
	for key := range x.w.state {
		if strings.HasPrefix(key, prefix) {
			keys = append(keys, key)
		}
	}
	sort.Strings(keys)
	values := [][]byte{}
	for _, key := range keys {
		values = append(values, x.w.state[key])
	}
	return values, nil
}
func (x *tx) SetEvent(name string, payload []byte) error {
	if x.event != nil {
		return fmt.Errorf("Fabric keeps one event per transaction")
	}
	x.event = payload
	return nil
}
func (x *tx) MSPID() (string, error) { return x.who.msp, nil }
func (x *tx) Attribute(name string) (string, bool, error) {
	switch name {
	case "hf.EnrollmentID":
		return x.who.id, true, nil
	case "role":
		return x.who.role, x.who.role != "", nil
	}
	return "", false, nil
}
func (x *tx) TxID() string                  { return x.id }
func (x *tx) Timestamp() (time.Time, error) { return x.w.clock, nil }

func (w *world) invoke(who identity, function string, args ...string) ([]byte, error) {
	w.txs++
	x := &tx{w: w, who: who, id: fmt.Sprintf("tx%04d", w.txs), writes: map[string][]byte{}}
	result, err := Invoke(x, function, args)
	if err != nil {
		return nil, err
	}
	for key, value := range x.writes {
		w.state[key] = value
	}
	if x.event != nil {
		var event Event
		_ = json.Unmarshal(x.event, &event)
		w.events = append(w.events, event)
	}
	return result, nil
}

func (w *world) must(who identity, function string, args ...string) []byte {
	w.t.Helper()
	result, err := w.invoke(who, function, args...)
	if err != nil {
		w.t.Fatalf("%s as %s: %v", function, who.id, err)
	}
	return result
}

func (w *world) refused(who identity, kind, function string, args ...string) {
	w.t.Helper()
	before := len(w.state)
	_, err := w.invoke(who, function, args...)
	if err == nil || !strings.HasPrefix(err.Error(), kind+":") {
		w.t.Fatalf("%s as %s: want %s error, got %v", function, who.id, kind, err)
	}
	if len(w.state) != before {
		w.t.Fatalf("%s as %s: a refused transaction changed the state", function, who.id)
	}
}

func (w *world) access(who identity, reportID string) Decision {
	w.t.Helper()
	var decision Decision
	if err := json.Unmarshal(w.must(who, "PDP:RequestAccess", reportID, "read"), &decision); err != nil {
		w.t.Fatal(err)
	}
	return decision
}

func hash(text string) string { return sha256Hex([]byte(text)) }

const consentRequired = `{"description":"Restricted results need an active consent for the requesting physician",
 "actions":["read"],
 "rules":[{"type":"subjectRole","value":"physician"},
          {"type":"consent","checks":["exists","grantee","patient","active","notExpired"]}]}`

// scenario builds steps 0-3 of the specification: policy, consent for exam A
// only (Ana, 30 days), restricted results A and B, each bound to the policy.
func scenario(t *testing.T) *world {
	w := newWorld(t)
	w.must(admin, "PAP:CreatePolicy", "ConsentRequiredPolicy", consentRequired)
	validUntil := clock0.Add(30 * 24 * time.Hour).Format(time.RFC3339)
	w.must(joao, "PIP:PutConsent", "consent-A", "sr-A", "pat-001", "phy-001", validUntil, hash("consent A"))
	w.must(lab, "PIP:PutResource", "report-A", "sr-A", "pat-001", hash("report A"), "R", "lab-001")
	w.must(lab, "PIP:PutResource", "report-B", "sr-B", "pat-001", hash("report B"), "R", "lab-001")
	w.must(admin, "PAP:BindResource", "resource:report-A", "ConsentRequiredPolicy")
	w.must(admin, "PAP:BindResource", "resource:report-B", "ConsentRequiredPolicy")
	return w
}
