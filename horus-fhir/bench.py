"""Measurements for the thesis evaluation (stage 6).

  python3 bench.py                 # uses the reports of .local/scenario-last.json
  python3 bench.py -n 30 -q 50 --throughput 60 --levels 1,5,10

1. Inside fhir-api (docker exec): RequestAccess submit->commit split into
   endorse / order / commit, PAP and PIP query latency, FHIR read + hash,
   throughput at several concurrency levels.
2. From the Mac: the full PEP round trip GET /reports/{id} (what a client sees).
Writes .local/bench-<timestamp>.json and .local/bench-last.md (tables).
It submits many RequestAccess transactions: run tools.py reset-demo afterwards.
"""
import argparse
import json
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import tools
from scenario import call

ROOT = Path(__file__).resolve().parent


def environment():
    stats = subprocess.run([tools.DOCKER, "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}"],
                           capture_output=True, text=True).stdout.splitlines()
    info = json.loads(subprocess.run([tools.DOCKER, "info", "--format", "{{json .}}"], capture_output=True, text=True).stdout)
    return {"host": platform.platform(), "dockerCpus": info.get("NCPU"), "dockerMemoryGiB": round(info.get("MemTotal", 0) / 2**30, 2),
            "fabric": "2.5.16 (1 Raft orderer, BatchTimeout 1s, MaxMessageCount 10)", "endorsement": tools.ENDORSEMENT,
            "hapi": "hapiproject/hapi:v8.0.0 (H2)",
            "kindRunning": any(line.startswith("scattered-training-control-plane") for line in stats),
            "containersMemory": stats}


def summary(values):
    """Same percentile rule as middleware/app/bench.py."""
    values = sorted(values)
    pick = lambda q: values[min(len(values) - 1, int(round(q * (len(values) - 1))))]
    return {"n": len(values), "mean": round(sum(values) / len(values), 2), "p50": round(pick(0.5), 2),
            "p95": round(pick(0.95), 2), "min": round(values[0], 2), "max": round(values[-1], 2)}


def table(title, rows, columns):
    lines = [f"**{title}**", "", "| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def stat_row(name, item):
    return [name, item.get("n"), item.get("mean"), item.get("p50"), item.get("p95"), item.get("max")]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("-n", type=int, default=30)
    parser.add_argument("-q", type=int, default=50)
    parser.add_argument("--throughput", type=int, default=60)
    parser.add_argument("--levels", default="1,5,10")
    args = parser.parse_args()
    evidence = json.loads((ROOT / ".local" / "scenario-last.json").read_text())
    reports = [step["report"] for step in evidence["steps"] if step.get("report")]
    permit = next(step["report"] for step in evidence["steps"] if step.get("expected") == "PERMIT")
    deny = next(step["report"] for step in evidence["steps"] if step.get("expected") == "NO_CONSENT")
    assert permit in reports and deny in reports
    print(f"bench: permit report {permit}, deny report {deny}; n={args.n} q={args.q} throughput={args.throughput} levels={args.levels}")
    started = datetime.now(timezone.utc)
    height_before = call("GET", "/status")[1]["chain"]["height"]
    inside = subprocess.run([tools.DOCKER, "exec", "fhir-api", "python", "-m", "app.bench", "--permit", permit, "--deny", deny,
                             "-n", str(args.n), "-q", str(args.q), "--throughput", str(args.throughput), "--levels", args.levels],
                            capture_output=True, text=True, check=True)
    result = json.loads(inside.stdout)
    pep, pdp = [], []
    for _ in range(args.n):
        start = time.perf_counter()
        code, outcome = call("GET", f"/reports/{permit}?as=phy-001")
        pep.append((time.perf_counter() - start) * 1000)
        assert code == 200, outcome
        pdp.append(outcome["timings"]["pdpSubmitMs"])
    result["pepEndToEndMs"] = summary(pep)
    result["environment"] = environment()
    result["parameters"] = vars(args)
    result["startedAt"], result["finishedAt"] = started.isoformat(), datetime.now(timezone.utc).isoformat()
    result["heightBefore"], result["heightAfter"] = height_before, call("GET", "/status")[1]["chain"]["height"]
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    (ROOT / ".local" / f"bench-{stamp}.json").write_text(json.dumps(result, indent=2) + "\n")

    columns = ["medida", "n", "média (ms)", "p50", "p95", "máx"]
    permit_series, deny_series = result["requestAccessPermit"], result["requestAccessDeny"]
    markdown = [f"Medido em {started.strftime('%d/%m/%Y %H:%M')} UTC · Docker {result['environment']['dockerCpus']} CPUs / "
                f"{result['environment']['dockerMemoryGiB']} GiB · kind ligado: {'sim' if result['environment']['kindRunning'] else 'não'} · "
                f"altura {height_before} → {result['heightAfter']}\n"]
    markdown.append(table("RequestAccess (PDP, submit até o commit)", [
        stat_row("PERMIT · endosso (Hospital AND Lab)", permit_series["endorseMs"]),
        stat_row("PERMIT · envio ao orderer", permit_series["orderMs"]),
        stat_row("PERMIT · espera do commit", permit_series["commitMs"]),
        stat_row("PERMIT · total", permit_series["totalMs"]),
        stat_row("DENY · total", deny_series["totalMs"]),
    ], columns))
    markdown.append(table("Consultas separadas (evaluate, sem transação)", [
        stat_row(name, item["gatewayMs"]) for name, item in result["queries"].items()
    ] + [stat_row("FHIR: ler DiagnosticReport + Observations", result["fhirReadMs"]),
         stat_row("hash SHA-256 do laudo", result["reportHashMs"]),
         stat_row("PEP ponta a ponta (GET /reports, pelo Mac)", result["pepEndToEndMs"])], columns))
    markdown.append(table("Vazão de RequestAccess", [
        [item["concurrency"], item["requests"], item["ok"], json.dumps(item["failures"]) if item["failures"] else "0",
         item["wallSeconds"], item["requestsPerSecond"], item["latencyMs"].get("p50"), item["latencyMs"].get("p95")]
        for item in result["throughput"]], ["concorrência", "pedidos", "ok", "falhas", "tempo (s)", "pedidos/s", "p50 (ms)", "p95 (ms)"]))
    (ROOT / ".local" / "bench-last.md").write_text("\n".join(markdown))
    print("\n".join(markdown))
    print(f"saved .local/bench-{stamp}.json and .local/bench-last.md")


if __name__ == "__main__":
    main()
