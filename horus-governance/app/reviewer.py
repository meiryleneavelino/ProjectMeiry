"""Input validation for reviewer eligibility.

The reviewer is no longer drawn here. The draw happens on the ledger through a
commit-reveal between the eligible organizations' SAST agents, so the Horus
server cannot influence (or re-roll) the result. This module only rejects
requests that could never have an eligible reviewer, before a transaction is
sent. The chaincode applies the same rule using the researcher's certificate.
"""

KNOWN_ORGANIZATIONS = ("UVA", "VU", "TUDELFT")


def eligible_reviewers(selected, researcher_organization):
    if (not isinstance(selected, list) or not selected or any(not isinstance(item, str) for item in selected)
            or len(selected) != len(set(selected))
            or any(organization not in KNOWN_ORGANIZATIONS for organization in selected)
            or researcher_organization not in KNOWN_ORGANIZATIONS):
        raise ValueError("Select distinct known organizations.")
    eligible = sorted(organization for organization in selected if organization != researcher_organization)
    if not eligible:
        raise ValueError("Select at least one reviewer outside the researcher's organization.")
    return eligible
