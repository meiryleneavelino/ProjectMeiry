package abac

import (
	"strconv"
	"time"
)

// Consent attributes (the consent is information, not policy). The FHIR
// Consent itself stays off-chain; only its hash and these fields are stored.
type Consent struct {
	ConsentID        string `json:"consentId"`
	ServiceRequestID string `json:"serviceRequestId"`
	PatientPseudo    string `json:"patientPseudo"`
	Grantee          string `json:"grantee"`
	ValidUntil       string `json:"validUntil"`
	ConsentHash      string `json:"consentHash"`
	Status           string `json:"status"`
	GrantedAt        string `json:"grantedAt"`
	RevokedAt        string `json:"revokedAt,omitempty"`
	TxID             string `json:"txId"`
}

// Resource attributes of a lab result (DiagnosticReport). The report itself
// stays in FHIR; the PEP recomputes its hash and compares with ReportHash.
type Resource struct {
	ReportID         string `json:"reportId"`
	ServiceRequestID string `json:"serviceRequestId"`
	PatientPseudo    string `json:"patientPseudo"`
	ReportHash       string `json:"reportHash"`
	SecurityLabel    string `json:"securityLabel"`
	LabID            string `json:"labId"`
	RegisteredAt     string `json:"registeredAt"`
	TxID             string `json:"txId"`
}

// AttributeReader is the only PIP surface the PDP sees.
type AttributeReader interface {
	Resource(reportID string) (*Resource, error)
	ConsentsForRequest(serviceRequestID string) ([]Consent, error)
}

// PIP is the Policy Information Point. Patients write their own consents;
// the lab writes resource attributes; subject attributes come from certificates.
type PIP struct{ ctx Context }

func (p PIP) PutConsent(consentID, serviceRequestID, patientPseudo, grantee, validUntil, consentHash string) (*Consent, error) {
	who, err := requireRole(p.ctx, RolePatient)
	if err != nil {
		return nil, err
	}
	if err := checkIDs("consentId", consentID, "serviceRequestId", serviceRequestID,
		"patientPseudo", patientPseudo, "grantee", grantee); err != nil {
		return nil, err
	}
	if err := checkHash("consentHash", consentHash); err != nil {
		return nil, err
	}
	if who.ID != patientPseudo {
		return nil, fail("forbidden", "only the patient %s can grant this consent", patientPseudo)
	}
	at, err := now(p.ctx)
	if err != nil {
		return nil, err
	}
	until, err := time.Parse(time.RFC3339, validUntil)
	if err != nil {
		return nil, fail("invalid", "validUntil must be RFC 3339")
	}
	if !until.After(at) {
		return nil, fail("invalid", "validUntil must be after the transaction time")
	}
	var existing Consent
	if found, err := load(p.ctx, "consent:"+consentID, &existing); err != nil || found {
		if err == nil {
			err = fail("conflict", "consent %s already exists", consentID)
		}
		return nil, err
	}
	consent := Consent{ConsentID: consentID, ServiceRequestID: serviceRequestID, PatientPseudo: patientPseudo,
		Grantee: grantee, ValidUntil: until.UTC().Format(timeLayout), ConsentHash: consentHash, Status: ConsentActive,
		GrantedAt: at.Format(timeLayout), TxID: p.ctx.TxID()}
	if err := store(p.ctx, "consent:"+consentID, consent); err != nil {
		return nil, err
	}
	if err := p.ctx.PutState("consentidx:"+serviceRequestID+":"+consentID, []byte(strconv.Quote(consentID))); err != nil {
		return nil, err
	}
	return &consent, emit(p.ctx, "PIP", "ConsentGranted", who.ID, at, map[string]string{"consentId": consentID,
		"serviceRequestId": serviceRequestID, "grantee": grantee, "validUntil": consent.ValidUntil, "consentHash": consentHash})
}

func (p PIP) RevokeConsent(consentID string) (*Consent, error) {
	who, err := requireRole(p.ctx, RolePatient)
	if err != nil {
		return nil, err
	}
	consent, err := p.GetConsent(consentID)
	if err != nil {
		return nil, err
	}
	if who.ID != consent.PatientPseudo {
		return nil, fail("forbidden", "only the patient %s can revoke this consent", consent.PatientPseudo)
	}
	if consent.Status != ConsentActive {
		return nil, fail("conflict", "consent %s is already %s", consentID, consent.Status)
	}
	at, err := now(p.ctx)
	if err != nil {
		return nil, err
	}
	consent.Status, consent.RevokedAt, consent.TxID = ConsentRevoked, at.Format(timeLayout), p.ctx.TxID()
	if err := store(p.ctx, "consent:"+consentID, consent); err != nil {
		return nil, err
	}
	return consent, emit(p.ctx, "PIP", "ConsentRevoked", who.ID, at, map[string]string{"consentId": consentID,
		"serviceRequestId": consent.ServiceRequestID, "grantee": consent.Grantee})
}

func (p PIP) GetConsent(consentID string) (*Consent, error) {
	var consent Consent
	found, err := load(p.ctx, "consent:"+consentID, &consent)
	if err != nil {
		return nil, err
	}
	if !found {
		return nil, fail("notfound", "consent %s does not exist", consentID)
	}
	return &consent, nil
}

// ConsentsForRequest returns every consent (any grantee, any status) given
// for one ServiceRequest.
func (p PIP) ConsentsForRequest(serviceRequestID string) ([]Consent, error) {
	ids, err := p.ctx.Range("consentidx:" + serviceRequestID + ":")
	if err != nil {
		return nil, err
	}
	consents := make([]Consent, 0, len(ids))
	for _, raw := range ids {
		id, err := strconv.Unquote(string(raw))
		if err != nil {
			return nil, err
		}
		consent, err := p.GetConsent(id)
		if err != nil {
			return nil, err
		}
		consents = append(consents, *consent)
	}
	return consents, nil
}

// GetConsentFor returns the consents of one ServiceRequest for one grantee.
func (p PIP) GetConsentFor(serviceRequestID, grantee string) ([]Consent, error) {
	all, err := p.ConsentsForRequest(serviceRequestID)
	if err != nil {
		return nil, err
	}
	matching := []Consent{}
	for _, consent := range all {
		if consent.Grantee == grantee {
			matching = append(matching, consent)
		}
	}
	return matching, nil
}

func (p PIP) ListConsents() ([]Consent, error) { return list[Consent](p.ctx, "consent:") }

func (p PIP) PutResource(reportID, serviceRequestID, patientPseudo, reportHash, securityLabel, labID string) (*Resource, error) {
	who, err := requireRole(p.ctx, RoleLab)
	if err != nil {
		return nil, err
	}
	if err := checkIDs("reportId", reportID, "serviceRequestId", serviceRequestID,
		"patientPseudo", patientPseudo, "labId", labID); err != nil {
		return nil, err
	}
	if err := checkHash("reportHash", reportHash); err != nil {
		return nil, err
	}
	if !labelPattern.MatchString(securityLabel) {
		return nil, fail("invalid", "securityLabel must match %s", labelPattern)
	}
	if who.ID != labID {
		return nil, fail("forbidden", "labId must be the invoking laboratory (%s)", who.ID)
	}
	if existing, err := p.Resource(reportID); err != nil || existing != nil {
		if err == nil {
			err = fail("conflict", "resource %s is already registered (results are immutable)", reportID)
		}
		return nil, err
	}
	at, err := now(p.ctx)
	if err != nil {
		return nil, err
	}
	resource := Resource{ReportID: reportID, ServiceRequestID: serviceRequestID, PatientPseudo: patientPseudo,
		ReportHash: reportHash, SecurityLabel: securityLabel, LabID: labID, RegisteredAt: at.Format(timeLayout), TxID: p.ctx.TxID()}
	if err := store(p.ctx, "resource:"+reportID, resource); err != nil {
		return nil, err
	}
	return &resource, emit(p.ctx, "PIP", "ResourceRegistered", who.ID, at, map[string]string{"reportId": reportID,
		"serviceRequestId": serviceRequestID, "reportHash": reportHash, "securityLabel": securityLabel})
}

// Resource returns nil (no error) when the resource is unknown.
func (p PIP) Resource(reportID string) (*Resource, error) {
	var resource Resource
	found, err := load(p.ctx, "resource:"+reportID, &resource)
	if err != nil || !found {
		return nil, err
	}
	return &resource, nil
}

func (p PIP) GetResource(reportID string) (*Resource, error) {
	resource, err := p.Resource(reportID)
	if err == nil && resource == nil {
		err = fail("notfound", "resource %s is not registered", reportID)
	}
	return resource, err
}

func (p PIP) ListResources() ([]Resource, error) { return list[Resource](p.ctx, "resource:") }

func itoa(value int) string { return strconv.Itoa(value) }
