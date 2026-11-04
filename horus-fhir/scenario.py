"""End-to-end scenario (steps 0-6) through the PEP API, standard library only.

  python3 scenario.py            # on top of the current state
  python3 scenario.py --reset    # tools.py reset-demo first (clean channel and FHIR)
  python3 scenario.py --revoke   # extra: João revokes, Dra. Ana is then denied (REVOKED)

Each step prints the FHIR IDs, the ABAC component called (PAP, PIP or PDP),
the Fabric transaction ID, the block number and the decision. The full
evidence is saved to .local/scenario-last.json. Exit status 0 only if every
access decision is the expected one. All data is fictitious; identities are
simulated with ?as= (not authentication).
"""
import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API = "http://127.0.0.1:8099"
NAMES = {"adm-001": "Admin", "pat-001": "João", "phy-001": "Dra. Ana", "phy-002": "Dr. Bruno", "lab-001": "Laboratório"}
evidence = {"startedAt": datetime.now(timezone.utc).isoformat(), "steps": []}


def call(method, path, body=None):
    token = (ROOT / ".local" / "api-token").read_text().strip()
    request = urllib.request.Request(API + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"null")
    except urllib.error.URLError as error:
        sys.exit(f"The PEP API is not reachable at {API} ({error.reason}). Run: python3 tools.py start")


def must(method, path, body=None):
    code, data = call(method, path, body)
    if code >= 400:
        sys.exit(f"{method} {path} failed: HTTP {code} {data}")
    return data


def header(number, actor, action):
    print(f"\n━━ Passo {number} · {actor} · {action}")


def line(label, value):
    print(f"   {label:<22} {value}")


def tx(receipt):
    return f"{receipt['txId'][:16]}…  bloco {receipt['blockNumber']}"


def record(step, **data):
    evidence["steps"].append({"step": step, **data})


def access(step, persona, report_id, exam, expected):
    header(step, NAMES[persona], f"abre {exam}")
    code, outcome = call("GET", f"/reports/{report_id}?as={persona}")
    decision = "PERMITIR" if outcome.get("permitted") else "NEGAR"
    print(f"   rastro da decisão:")
    print(f"     PEP  GET /reports/{report_id}?as={persona} → submit PDP:RequestAccess")
    for item in outcome.get("decisionTrace", []):
        attributes = item.get("attributes") or {}
        shown = ", ".join(f"{key}={value[:16] + '…' if len(value) > 20 else value}" for key, value in attributes.items())
        print(f"     {item['component']:<4} {item['action']}: {item['result']}" + (f"  [{shown}]" if shown else ""))
    print(f"     PDP  decisão: {decision} ({outcome.get('reason')})")
    if outcome.get("hashCheck"):
        check = outcome["hashCheck"]
        print(f"     PEP  hash FHIR == PIP: {'sim' if check['match'] else 'NÃO'} ({check['computed'][:16]}…)")
    line("componente ABAC", "PEP → PDP (consulta PAP e PIP)")
    line("transação Fabric", f"{outcome.get('txId', '')[:16]}…  bloco {outcome.get('blockNumber')}")
    line("HTTP / decisão", f"{code} · {decision} · {outcome.get('reason')}")
    line("conteúdo entregue", "sim (DiagnosticReport + Observations)" if "resource" in outcome else "não (só o motivo)")
    line("AuditEvent (FHIR)", outcome.get("auditEventId"))
    line("tempo PDP (submit)", f"{outcome.get('timings', {}).get('pdpSubmitMs')} ms")
    ok = (outcome.get("reason") == expected) and (code == (200 if expected == "PERMIT" else 403))
    record(step, actor=persona, report=report_id, http=code, reason=outcome.get("reason"), expected=expected, ok=ok,
           txId=outcome.get("txId"), blockNumber=outcome.get("blockNumber"), auditEventId=outcome.get("auditEventId"),
           trace=outcome.get("decisionTrace"), timings=outcome.get("timings"))
    return ok, outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--reset", action="store_true", help="run tools.py reset-demo first")
    parser.add_argument("--revoke", action="store_true", help="extra: João revokes the consent; Ana is then denied")
    arguments = parser.parse_args()
    if arguments.reset:
        print("reset-demo (canal e FHIR limpos)…")
        subprocess.run([sys.executable, str(ROOT / "tools.py"), "reset-demo"], check=True, capture_output=True)
    status = must("GET", "/status")
    print(f"Ledger: {status['ledger']} · altura inicial {status['chain']['height']} · FHIR {status['fhir']['fhirVersion']}")
    print("Identidade simulada (?as=), não é autenticação. Dados fictícios.")

    header(0, "Admin", "cadastra a política ConsentRequiredPolicy")
    code, created = call("POST", "/admin/policies?as=adm-001", {})
    if code == 409:
        policy = next(item for item in must("GET", "/policies")["policies"] if item["policyId"] == "ConsentRequiredPolicy")
        line("componente ABAC", "PAP (já existia: reaproveitada)")
        line("transação Fabric", f"{policy['txId'][:16]}… (original)")
    elif code == 200:
        policy = created["policy"]
        line("componente ABAC", "PAP: CreatePolicy → PolicyCreated")
        line("transação Fabric", tx(created))
    else:
        sys.exit(f"policy creation failed: HTTP {code} {created}")
    line("política", f"{policy['policyId']} v{policy['version']}  hash {policy['policyHash'][:16]}…")
    line("regras", "; ".join(f"{rule['type']}={rule.get('value') or ','.join(rule.get('checks', []))}" for rule in policy["rules"]))
    record(0, actor="adm-001", component="PAP", policy=policy)

    header(1, "Dra. Ana", "solicita Exame A (hemograma) e Exame B (sorologia) para João")
    orders = must("POST", "/service-requests?as=phy-001")
    for item in orders["serviceRequests"]:
        line(f"ServiceRequest {item['id']}", f"{item['exam']} · solicitante {item['requester']}")
    line("componente ABAC", "— (sem registro na ledger)")
    record(1, actor="phy-001", fhir=orders["serviceRequests"])

    header(2, "João", "consente: só a Dra. Ana, só o Exame A, por 30 dias (não consente o B)")
    consent = must("POST", "/consents?as=pat-001", {"serviceRequestId": "sr-001", "grantee": "phy-001", "days": 30})
    line("Consent (FHIR)", f"{consent['fhir']['id']} (active, só sr-001)")
    line("componente ABAC", "PIP: PutConsent → ConsentGranted")
    line("atributos on-chain", f"grantee={consent['onChain']['grantee']}, validUntil={consent['onChain']['validUntil']}")
    line("consentHash", consent["consentHash"][:32] + "…")
    line("transação Fabric", tx(consent))
    record(2, actor="pat-001", component="PIP", fhir=consent["fhir"], consentHash=consent["consentHash"],
           txId=consent["txId"], blockNumber=consent["blockNumber"])

    header(3, "Laboratório", "armazena os resultados A e B, marcados como restritos (R)")
    reports = {}
    for request_id, exam in (("sr-001", "Exame A"), ("sr-002", "Exame B")):
        result = must("POST", "/lab/results?as=lab-001", {"serviceRequestId": request_id, "securityLabel": "R"})
        reports[request_id] = result["fhir"]["diagnosticReport"]
        print(f"   {exam}:")
        line("  DiagnosticReport", f"{result['fhir']['diagnosticReport']} (meta.security R)")
        line("  Observations", ", ".join(result["fhir"]["observations"]))
        line("  Provenance", result["fhir"]["provenance"])
        line("  reportHash", result["reportHash"][:32] + "…")
        line("  PIP PutResource", tx(result["pip"]))
        line("  PAP BindResource", tx(result["pap"]) + " (assinado por adm-001)")
        record(3, actor="lab-001", component="PIP+PAP", exam=exam, fhir=result["fhir"], reportHash=result["reportHash"],
               pip={"txId": result["pip"]["txId"], "blockNumber": result["pip"]["blockNumber"]},
               pap={"txId": result["pap"]["txId"], "blockNumber": result["pap"]["blockNumber"]})

    results = [access(4, "phy-001", reports["sr-001"], "Exame A", "PERMIT"),
               access(5, "phy-001", reports["sr-002"], "Exame B", "NO_CONSENT"),
               access("extra", "phy-002", reports["sr-001"], "Exame A", "WRONG_GRANTEE")]
    if arguments.revoke:
        header("extra", "João", "revoga o consentimento do Exame A")
        revoked = must("POST", f"/consents/{consent['fhir']['id']}/revoke?as=pat-001")
        line("componente ABAC", "PIP: RevokeConsent → ConsentRevoked")
        line("transação Fabric", tx(revoked))
        line("Consent (FHIR)", f"{consent['fhir']['id']} → inactive (versão {revoked['fhir']['versionId']})")
        record("extra-revoke", actor="pat-001", txId=revoked["txId"], blockNumber=revoked["blockNumber"])
        results.append(access("extra", "phy-001", reports["sr-001"], "Exame A (após revogação)", "REVOKED"))

    header(6, "PEP", "registra cada decisão (AuditEvent com referência à tx on-chain)")
    accesses = {outcome["txId"] for _, outcome in results}
    events = [item for item in must("GET", "/audit") if item["source"] == "off-chain" and item["txId"] in accesses]
    for event in events:
        chain = must("GET", f"/transactions/{event['txId']}")
        decision = next(item for item in must("GET", "/audit")
                        if item["source"] == "on-chain" and item["txId"] == event["txId"])
        line(f"AuditEvent {event['id']}", f"{event['actor']} · {event['detail']['decision']}"
                                           + ("" if event["detail"]["reason"] == "PERMIT" else f" ({event['detail']['reason']})"))
        line("  → tx on-chain", f"{event['txId'][:16]}… bloco {chain.get('blockNumber')} {chain['validationCode']} "
                                f"· {decision['name']} gravado pelo PDP")
        record(6, auditEventId=event["id"], txId=event["txId"], validationCode=chain["validationCode"],
               blockNumber=chain.get("blockNumber"))

    final = must("GET", "/status")["chain"]["height"]
    print("\n━━ Resumo")
    for ok, outcome in results:
        print(f"   {'OK ' if ok else 'ERRO'} {outcome.get('reason'):<14} tx {outcome.get('txId', '')[:12]}… bloco {outcome.get('blockNumber')}")
    print(f"   altura final do fhir-channel: {final}")
    evidence.update(finishedAt=datetime.now(timezone.utc).isoformat(), finalHeight=final,
                    allExpected=all(ok for ok, _ in results))
    path = ROOT / ".local" / "scenario-last.json"
    path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    print(f"   evidência completa: {path.relative_to(ROOT)}")
    return 0 if evidence["allExpected"] else 1


if __name__ == "__main__":
    sys.exit(main())
