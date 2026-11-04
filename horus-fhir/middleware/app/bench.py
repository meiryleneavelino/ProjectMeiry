"""Measurements run INSIDE fhir-api (docker exec), so no extra route is exposed.

  python -m app.bench --permit <reportId> --deny <reportId> [-n 30] [-q 50] [--throughput 60]

Prints one JSON document: RequestAccess latency split into endorse / order /
commit, PAP and PIP query latency (evaluate), FHIR read + hash, and throughput
of RequestAccess at several concurrency levels. Fabric has no gas.
"""
import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

from . import hashing
from .fabric_client import FabricClient, LedgerError
from .fhir_client import FhirClient
from .pep import PEP
from .settings import Settings


def summary(values):
    values = sorted(values)
    if not values:
        return {}
    pick = lambda q: values[min(len(values) - 1, int(round(q * (len(values) - 1))))]
    return {"n": len(values), "mean": round(statistics.fmean(values), 2), "p50": round(pick(0.5), 2),
            "p95": round(pick(0.95), 2), "min": round(values[0], 2), "max": round(values[-1], 2)}


def timed(function):
    start = time.perf_counter()
    result = function()
    return result, (time.perf_counter() - start) * 1000


def request_access_series(ledger, persona, report, n):
    phases = {"endorseMs": [], "orderMs": [], "commitMs": [], "totalMs": [], "clientMs": []}
    reasons = {}
    for _ in range(n):
        receipt, client_ms = timed(lambda: ledger.request_access(persona, report))
        for key in ("endorseMs", "orderMs", "commitMs", "totalMs"):
            phases[key].append(receipt["timings"][key])
        phases["clientMs"].append(client_ms)
        reasons[receipt["result"]["reason"]] = reasons.get(receipt["result"]["reason"], 0) + 1
    return {"reasons": reasons, **{key: summary(values) for key, values in phases.items()}}


def query_series(ledger, n, function, *args):
    gateway, client = [], []
    for _ in range(n):
        start = time.perf_counter()
        response = ledger._call("POST", "/evaluate", {"as": "phy-001", "function": function, "args": list(args)})
        client.append((time.perf_counter() - start) * 1000)
        gateway.append(response["timings"]["totalMs"])
    return {"gatewayMs": summary(gateway), "clientMs": summary(client)}


def throughput(ledger, persona, report, total, concurrency):
    latencies, failures = [], {}

    def one(_):
        start = time.perf_counter()
        try:
            ledger.request_access(persona, report)
            latencies.append((time.perf_counter() - start) * 1000)
        except LedgerError as error:
            key = "MVCC_READ_CONFLICT" if "MVCC" in error.detail else error.kind
            failures[key] = failures.get(key, 0) + 1

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(one, range(total)))
    wall = time.perf_counter() - start
    return {"concurrency": concurrency, "requests": total, "ok": len(latencies), "failures": failures,
            "wallSeconds": round(wall, 2), "requestsPerSecond": round(len(latencies) / wall, 2),
            "latencyMs": summary(latencies)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--permit", required=True)
    parser.add_argument("--deny", required=True)
    parser.add_argument("--request", default="sr-001")
    parser.add_argument("-n", type=int, default=30)
    parser.add_argument("-q", type=int, default=50)
    parser.add_argument("--throughput", type=int, default=60)
    parser.add_argument("--levels", default="1,5,10")
    args = parser.parse_args()
    settings = Settings.load()
    ledger = FabricClient(settings.gateway_url, settings.gateway_token)
    fhir = FhirClient(settings.fhir_base)
    pep = PEP(fhir, ledger, settings)

    fhir_read, hash_ms = [], []
    for _ in range(args.q):
        (report, observations), elapsed = timed(lambda: pep.read_report(args.permit))
        fhir_read.append(elapsed)
        _, elapsed = timed(lambda: hashing.report_hash(report, observations))
        hash_ms.append(elapsed)

    result = {
        "requestAccessPermit": request_access_series(ledger, "phy-001", args.permit, args.n),
        "requestAccessDeny": request_access_series(ledger, "phy-001", args.deny, args.n),
        "queries": {
            "PAP:GetPolicyForResource": query_series(ledger, args.q, "PAP:GetPolicyForResource", args.permit, "R"),
            "PIP:GetResource": query_series(ledger, args.q, "PIP:GetResource", args.permit),
            "PIP:GetConsentFor": query_series(ledger, args.q, "PIP:GetConsentFor", args.request, "phy-001"),
        },
        "fhirReadMs": summary(fhir_read),
        "reportHashMs": summary(hash_ms),
        "throughput": [throughput(ledger, "phy-001", args.permit, args.throughput, int(level))
                       for level in args.levels.split(",")],
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
