"""Fictitious FHIR R4 resources: the seed (step 1 of the scenario) and the
builders for Consent, lab results, Provenance and AuditEvent."""
import secrets
from datetime import datetime, timedelta, timezone

LOINC = "http://loinc.org"
CONFIDENTIALITY = "http://terminology.hl7.org/CodeSystem/v3-Confidentiality"
LABEL_DISPLAY = {"R": "restricted", "N": "normal", "V": "very restricted"}
EXAM_CODES = {
    "sr-001": {"code": "58410-2", "display": "CBC panel - Blood by Automated count", "text": "Hemograma"},
    "sr-002": {"code": "5196-1", "display": "Hepatitis B virus surface Ag [Presence] in Serum", "text": "Sorologia (HBsAg)"},
}
# Default fictitious values per ServiceRequest (used when the lab sends none).
DEFAULT_RESULTS = {
    "sr-001": [{"code": "718-7", "display": "Hemoglobin [Mass/volume] in Blood", "value": 13.8, "unit": "g/dL"},
               {"code": "6690-2", "display": "Leukocytes [#/volume] in Blood", "value": 6.2, "unit": "10*3/uL"},
               {"code": "777-3", "display": "Platelets [#/volume] in Blood", "value": 250, "unit": "10*3/uL"}],
    "sr-002": [{"code": "5196-1", "display": "Hepatitis B virus surface Ag [Presence] in Serum", "text": "Negative"}],
}


def now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def opaque(prefix: str) -> str:
    """IDs that may appear on-chain carry no clinical meaning."""
    return f"{prefix}-{secrets.token_hex(6)}"


def code(system, value, display=None):
    coding = {"system": system, "code": value}
    if display:
        coding["display"] = display
    return coding


def seed_resources() -> list:
    hospital = {"resourceType": "Organization", "id": "org-hospital-001", "active": True, "name": "Hospital Horus (fictício)"}
    lab = {"resourceType": "Organization", "id": "org-lab-001", "active": True, "name": "Laboratório Horus (fictício)"}
    patient = {"resourceType": "Patient", "id": "patient-001", "active": True, "gender": "male", "birthDate": "1980-01-01",
               "name": [{"family": "Silva", "given": ["João"], "text": "João Silva (fictício)"}]}
    practitioners = [
        {"resourceType": "Practitioner", "id": "practitioner-001", "active": True,
         "name": [{"family": "Souza", "given": ["Ana"], "prefix": ["Dra."], "text": "Dra. Ana Souza (fictícia)"}]},
        {"resourceType": "Practitioner", "id": "practitioner-002", "active": True,
         "name": [{"family": "Lima", "given": ["Bruno"], "prefix": ["Dr."], "text": "Dr. Bruno Lima (fictício)"}]}]
    roles = [{"resourceType": "PractitionerRole", "id": f"role-00{index}", "active": True,
              "practitioner": {"reference": f"Practitioner/practitioner-00{index}"},
              "organization": {"reference": "Organization/org-hospital-001"},
              "code": [{"coding": [code("http://terminology.hl7.org/CodeSystem/practitioner-role", "doctor", "Doctor")]}]}
             for index in (1, 2)]
    return [hospital, lab, patient, *practitioners, *roles]


def service_requests(requester_ref: str, patient_ref: str = "Patient/patient-001") -> list:
    """Step 1: the physician orders exam A (sr-001) and exam B (sr-002)."""
    return [{"resourceType": "ServiceRequest", "id": request_id, "status": "active", "intent": "order",
             "code": {"coding": [code(LOINC, exam["code"], exam["display"])], "text": exam["text"]},
             "subject": {"reference": patient_ref}, "requester": {"reference": requester_ref},
             "performer": [{"reference": "Organization/org-lab-001"}],
             "authoredOn": iso(now())} for request_id, exam in EXAM_CODES.items()]


def consent(consent_id, patient_ref, grantee_ref, request_id, start: datetime, end: datetime) -> dict:
    return {
        "resourceType": "Consent", "id": consent_id, "status": "active",
        "scope": {"coding": [code("http://terminology.hl7.org/CodeSystem/consentscope", "patient-privacy", "Privacy Consent")]},
        "category": [{"coding": [code(LOINC, "59284-0", "Patient Consent")]}],
        "patient": {"reference": patient_ref}, "dateTime": iso(start),
        "policyRule": {"coding": [code("http://terminology.hl7.org/CodeSystem/v3-ActCode", "OPTIN", "opt-in")]},
        "provision": {
            "type": "permit", "period": {"start": iso(start), "end": iso(end)},
            "actor": [{"role": {"coding": [code("http://terminology.hl7.org/CodeSystem/v3-ParticipationType", "IRCP",
                                                 "information recipient")]},
                       "reference": {"reference": grantee_ref}}],
            "action": [{"coding": [code("http://terminology.hl7.org/CodeSystem/consentaction", "access", "Access")]}],
            "data": [{"meaning": "related", "reference": {"reference": f"ServiceRequest/{request_id}"}}],
        },
    }


def lab_results(request: dict, label: str, lab_ref: str, values: list) -> tuple[dict, list, dict]:
    """Observations + DiagnosticReport (both with meta.security) + Provenance."""
    security = {"security": [code(CONFIDENTIALITY, label, LABEL_DISPLAY.get(label))]}
    issued = iso(now())
    observations = []
    for item in values:
        observation = {"resourceType": "Observation", "id": opaque("obs"), "meta": dict(security), "status": "final",
                       "code": {"coding": [code(LOINC, item["code"], item.get("display"))]},
                       "subject": request["subject"], "basedOn": [{"reference": f"ServiceRequest/{request['id']}"}],
                       "performer": [{"reference": lab_ref}], "issued": issued}
        if "value" in item:
            observation["valueQuantity"] = {"value": item["value"], "unit": item["unit"],
                                            "system": "http://unitsofmeasure.org", "code": item["unit"]}
        else:
            observation["valueString"] = item["text"]
        observations.append(observation)
    report = {"resourceType": "DiagnosticReport", "id": opaque("dr"), "meta": dict(security), "status": "final",
              "code": request["code"], "subject": request["subject"],
              "basedOn": [{"reference": f"ServiceRequest/{request['id']}"}],
              "performer": [{"reference": lab_ref}], "issued": issued,
              "result": [{"reference": f"Observation/{item['id']}"} for item in observations]}
    provenance = {"resourceType": "Provenance", "id": opaque("prov"), "recorded": issued,
                  "target": [{"reference": f"DiagnosticReport/{report['id']}"},
                             *({"reference": f"Observation/{item['id']}"} for item in observations)],
                  "agent": [{"type": {"coding": [code("http://terminology.hl7.org/CodeSystem/provenance-participant-type",
                                                      "author", "Author")]},
                             "who": {"reference": lab_ref}}]}
    return report, observations, provenance


def audit_event(agent_ref, persona_id, report_id, permitted, reason, tx_id, block, channel="fhir-channel") -> dict:
    """Off-chain record of what the PEP enforced, pointing to the on-chain tx."""
    details = [("decision", "PERMIT" if permitted else "DENY"), ("reason", reason), ("channel", channel),
               ("fabricTxId", tx_id or "none"), ("fabricBlock", str(block) if block is not None else "none"),
               ("persona", persona_id)]
    agent = {"type": {"coding": [code("http://terminology.hl7.org/CodeSystem/v3-ParticipationType", "IRCP",
                                      "information recipient")]},
             "altId": persona_id, "requestor": True}
    if agent_ref:
        agent["who"] = {"reference": agent_ref}
    return {
        "resourceType": "AuditEvent",
        "type": code("http://terminology.hl7.org/CodeSystem/audit-event-type", "rest", "RESTful Operation"),
        "subtype": [code("http://hl7.org/fhir/restful-interaction", "read", "read")],
        "action": "R", "recorded": iso(now()), "outcome": "0" if permitted else "4",
        "outcomeDesc": f"{'PERMIT' if permitted else 'DENY'} {reason} (tx {tx_id or 'none'})",
        "agent": [agent],
        "source": {"observer": {"display": "horus-fhir PEP"},
                   "type": [code("http://terminology.hl7.org/CodeSystem/security-source-type", "4", "Application Server")]},
        "entity": [{"what": {"reference": f"DiagnosticReport/{report_id}"},
                    "type": code("http://terminology.hl7.org/CodeSystem/audit-entity-type", "2", "System Object"),
                    "detail": [{"type": name, "valueString": value} for name, value in details]}],
    }


def valid_until(days: int) -> tuple[datetime, datetime]:
    start = now()
    return start, start + timedelta(days=days)
