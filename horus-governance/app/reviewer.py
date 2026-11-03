import hashlib
import secrets


KNOWN_ORGANIZATIONS = ("UVA", "VU", "TUDELFT")


def select_reviewer(selected, researcher_organization, seed=None):
    if (not isinstance(selected, list) or not selected or any(not isinstance(item, str) for item in selected)
            or len(selected) != len(set(selected))
            or any(organization not in KNOWN_ORGANIZATIONS for organization in selected)
            or researcher_organization not in KNOWN_ORGANIZATIONS):
        raise ValueError("Select distinct known organizations.")
    eligible = sorted(organization for organization in selected if organization != researcher_organization)
    if not eligible:
        raise ValueError("Select at least one reviewer outside the researcher's organization.")
    seed = seed or secrets.token_hex(32)
    seed_bytes = bytes.fromhex(seed)
    reviewer = min(eligible, key=lambda organization: hashlib.sha256(seed_bytes + organization.encode()).digest())
    return {"reviewer": reviewer, "eligible": eligible, "excluded": researcher_organization,
            "seed": seed, "selection_version": "sha256-rank-v1"}