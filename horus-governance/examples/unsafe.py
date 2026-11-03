import pickle
import requests
import subprocess

API_TOKEN = "FAKE_HORUS_TOKEN_FOR_STATIC_ANALYSIS_ONLY"


def unsafe_training(text, serialized):
    result = eval(text)
    restored = pickle.loads(serialized)
    subprocess.run(["echo", "static-analysis-example"])
    requests.get("https://example.invalid", headers={"Authorization": API_TOKEN})
    return result, restored