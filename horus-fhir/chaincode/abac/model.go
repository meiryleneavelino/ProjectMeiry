// Package abac holds the fhir-abac chaincode rules: PAP (policies), PIP
// (attributes) and PDP (decisions), XACML style, in one chaincode. It is pure
// Go over the Context interface so it runs unchanged in unit tests.
//
// Privacy: only pseudonymous IDs, SHA-256 hashes, deadlines, statuses and
// decisions are stored. No clinical data ever reaches this package.
package abac

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"regexp"
	"time"
)

// Context is what the chaincode needs from Fabric (see cmd/fhir-abac).
type Context interface {
	GetState(key string) ([]byte, error)
	PutState(key string, value []byte) error
	// Range returns the values of all keys starting with prefix, in key order.
	Range(prefix string) ([][]byte, error)
	SetEvent(name string, payload []byte) error
	MSPID() (string, error)
	// Attribute reads an attribute of the invoker's X.509 certificate.
	Attribute(name string) (string, bool, error)
	TxID() string
	// Timestamp is the transaction timestamp (same on every endorsing peer).
	Timestamp() (time.Time, error)
}

const (
	HospitalMSP = "HospitalMSP"
	LabMSP      = "LabMSP"

	RoleAdmin     = "admin"
	RolePatient   = "patient"
	RolePhysician = "physician"
	RoleLab       = "lab"

	ConsentActive  = "active"
	ConsentRevoked = "revoked"

	timeLayout = time.RFC3339Nano
)

// roleIssuer pins every role to the only MSP allowed to issue it: any CA can
// put any attribute in a certificate, so a "role=admin" issued by the lab's CA
// must not count.
var roleIssuer = map[string]string{
	RoleAdmin: HospitalMSP, RolePatient: HospitalMSP, RolePhysician: HospitalMSP, RoleLab: LabMSP,
}

// Fixed denial reasons returned by the PDP.
const (
	ReasonPermit            = "PERMIT"
	ReasonUnknownResource   = "UNKNOWN_RESOURCE"
	ReasonNoPolicy          = "NO_POLICY"
	ReasonActionNotAllowed  = "ACTION_NOT_ALLOWED"
	ReasonNotPhysician      = "NOT_PHYSICIAN"
	ReasonWrongRole         = "WRONG_ROLE"
	ReasonWrongOrganization = "WRONG_ORGANIZATION"
	ReasonLabelMismatch     = "LABEL_MISMATCH"
	ReasonNoConsent         = "NO_CONSENT"
	ReasonWrongGrantee      = "WRONG_GRANTEE"
	ReasonPatientMismatch   = "PATIENT_MISMATCH"
	ReasonRevoked           = "REVOKED"
	ReasonExpired           = "EXPIRED"
)

var (
	idPattern    = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`)
	hashPattern  = regexp.MustCompile(`^[0-9a-f]{64}$`)
	labelPattern = regexp.MustCompile(`^[A-Za-z0-9_-]{1,32}$`)
	wordPattern  = regexp.MustCompile(`^[a-z][a-zA-Z]{0,31}$`)
)

// Error carries a stable kind prefix: invalid, forbidden, conflict, notfound.
type Error struct{ Kind, Message string }

func (e *Error) Error() string { return e.Kind + ": " + e.Message }

func fail(kind, format string, args ...any) error {
	return &Error{Kind: kind, Message: fmt.Sprintf(format, args...)}
}

// Subject is the invoker, read only from its certificate (never from state).
type Subject struct {
	ID   string `json:"id"`
	MSP  string `json:"msp"`
	Role string `json:"role"`
}

func subject(ctx Context) (Subject, error) {
	msp, err := ctx.MSPID()
	if err != nil {
		return Subject{}, err
	}
	id, found, err := ctx.Attribute("hf.EnrollmentID")
	if err != nil || !found || !idPattern.MatchString(id) {
		return Subject{}, fail("forbidden", "the certificate has no valid hf.EnrollmentID")
	}
	role, _, err := ctx.Attribute("role")
	if err != nil {
		return Subject{}, err
	}
	if roleIssuer[role] != msp {
		role = "" // unknown role, or a role issued by an MSP that may not issue it
	}
	return Subject{ID: id, MSP: msp, Role: role}, nil
}

func requireRole(ctx Context, role string) (Subject, error) {
	who, err := subject(ctx)
	if err != nil {
		return who, err
	}
	if who.Role != role {
		return who, fail("forbidden", "requires role=%s issued by %s", role, roleIssuer[role])
	}
	return who, nil
}

func checkID(field, value string) error {
	if !idPattern.MatchString(value) {
		return fail("invalid", "%s must match %s", field, idPattern)
	}
	return nil
}

// checkIDs validates field/value pairs in a fixed order (deterministic errors).
func checkIDs(pairs ...string) error {
	for index := 0; index+1 < len(pairs); index += 2 {
		if err := checkID(pairs[index], pairs[index+1]); err != nil {
			return err
		}
	}
	return nil
}

func checkHash(field, value string) error {
	if !hashPattern.MatchString(value) {
		return fail("invalid", "%s must be a lowercase hex SHA-256", field)
	}
	return nil
}

func now(ctx Context) (time.Time, error) {
	stamp, err := ctx.Timestamp()
	return stamp.UTC(), err
}

// Canonical returns JSON with sorted object keys, no insignificant whitespace,
// UTF-8 and no HTML escaping: the format all hashes in this module use.
func Canonical(value any) ([]byte, error) {
	raw, err := json.Marshal(value)
	if err != nil {
		return nil, err
	}
	var generic any
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if err := decoder.Decode(&generic); err != nil {
		return nil, err
	}
	var buffer bytes.Buffer
	encoder := json.NewEncoder(&buffer)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(generic); err != nil {
		return nil, err
	}
	return bytes.TrimRight(buffer.Bytes(), "\n"), nil
}

func sha256Hex(data []byte) string {
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

func load(ctx Context, key string, target any) (bool, error) {
	raw, err := ctx.GetState(key)
	if err != nil || raw == nil {
		return false, err
	}
	return true, json.Unmarshal(raw, target)
}

func store(ctx Context, key string, value any) error {
	raw, err := Canonical(value)
	if err != nil {
		return err
	}
	return ctx.PutState(key, raw)
}

func list[T any](ctx Context, prefix string) ([]T, error) {
	values, err := ctx.Range(prefix)
	if err != nil {
		return nil, err
	}
	items := make([]T, 0, len(values))
	for _, raw := range values {
		var item T
		if err := json.Unmarshal(raw, &item); err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	return items, nil
}

// Event is emitted once per write transaction (Fabric keeps one chaincode
// event per transaction) and also indexed under evt: for the audit timeline.
type Event struct {
	Name      string            `json:"name"`
	TxID      string            `json:"txId"`
	Timestamp string            `json:"timestamp"`
	Actor     string            `json:"actor"`
	Component string            `json:"component"`
	Detail    map[string]string `json:"detail"`
}

func emit(ctx Context, component, name, actor string, at time.Time, detail map[string]string) error {
	event := Event{Name: name, TxID: ctx.TxID(), Timestamp: at.Format(timeLayout), Actor: actor,
		Component: component, Detail: detail}
	raw, err := Canonical(event)
	if err != nil {
		return err
	}
	if err := ctx.SetEvent(name, raw); err != nil {
		return err
	}
	return ctx.PutState(fmt.Sprintf("evt:%020d:%s", at.UnixNano(), ctx.TxID()), raw)
}
