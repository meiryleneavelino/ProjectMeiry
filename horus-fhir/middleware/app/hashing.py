"""SHA-256 of canonical JSON (sorted keys, no whitespace, UTF-8).

Hashes are always computed over resources as READ BACK from the FHIR server,
without the fields the server manages (meta.versionId, meta.lastUpdated,
meta.source) and without the generated narrative (text), so the same content
always gives the same hash.
"""
import copy
import hashlib
import json

SERVER_META = ("versionId", "lastUpdated", "source")


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def strip(resource: dict) -> dict:
    clean = copy.deepcopy(resource)
    clean.pop("text", None)
    meta = clean.get("meta")
    if isinstance(meta, dict):
        for field in SERVER_META:
            meta.pop(field, None)
        if not meta:
            clean.pop("meta")
    return clean


def resource_hash(resource: dict) -> str:
    return sha256(strip(resource))


def report_hash(report: dict, observations: list) -> str:
    """The DiagnosticReport together with its Observations (the values live there)."""
    return sha256({"diagnosticReport": strip(report),
                   "observations": sorted((strip(item) for item in observations), key=lambda item: item["id"])})
