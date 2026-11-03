import json
import time
import urllib.error
import urllib.request

from manage import LOCAL


def request(path, payload=None, authenticated=True):
    access = json.loads((LOCAL / "access.json").read_text())
    headers = {"Content-Type": "application/json"}
    if authenticated:
        headers["Authorization"] = f"Bearer {access['token']}"
    operation = urllib.request.Request(access["url"] + path, headers=headers,
                                       data=json.dumps(payload).encode() if payload is not None else None)
    with urllib.request.urlopen(operation, timeout=70) as response:
        return response.status, json.load(response)


def expect_error(path, code, payload=None, authenticated=True):
    try:
        request(path, payload, authenticated)
    except urllib.error.HTTPError as error:
        assert error.code == code, f"Expected {code}, got {error.code}"
    else:
        raise AssertionError("Request unexpectedly succeeded")


def main():
    expect_error("/catalog", 401, authenticated=False)
    expect_error("/runs", 422, {"organizations": ["UVA", "TUDELFT"], "algorithm": "arbitrary-script"})
    code, record = request("/runs", {"algorithm": "logistic-regression-v1", "dataset_id": "synthetic-local-v1",
                                    "organizations": ["UVA", "VU", "TUDELFT"], "rounds": 3, "local_epochs": 2})
    assert code == 202
    run_id = record["id"]
    print(f"Run {run_id}: three organizations, three federated rounds")
    expect_error(f"/runs/{run_id}/model", 409)
    deadline = time.monotonic() + 600
    previous_state = None
    while time.monotonic() < deadline:
        _, record = request(f"/runs/{run_id}")
        state = (record["status"], record["completed_rounds"])
        if state != previous_state:
            print(f"Status: {state[0]}; completed rounds: {state[1]}")
            previous_state = state
        if record["status"] in ("failed", "cancelled", "interrupted"):
            raise RuntimeError(record.get("error", record["status"]))
        if record["status"] == "completed":
            break
        time.sleep(1)
    else:
        request(f"/runs/{run_id}/cancel", {})
        raise RuntimeError("Training exceeded the test deadline")
    _, model = request(f"/runs/{run_id}/model")
    assert model["format"] == "dynamos-logistic-regression-v1"
    assert set(model["organizations"]) == {"UVA", "VU", "TUDELFT"}
    assert model["rounds"] == 3
    assert set(model) == {"format", "algorithm", "features", "classes", "organizations", "rounds", "coefficients", "intercept"}
    assert len(record["round_history"]) == 3
    (LOCAL / "test-model.json").write_text(json.dumps(model, indent=2))
    (LOCAL / "training-report.json").write_text(json.dumps(record, indent=2))
    print("PASS: final global model downloaded; no dataset, raw predictions or local model downloads exposed")


if __name__ == "__main__":
    main()