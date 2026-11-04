"""HAPI FHIR R4 client. The FHIR server is reachable only inside horus-fhir-net:
the browser never talks to it, every read of a result goes through the PEP."""
import httpx


class FhirError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


class FhirClient:
    def __init__(self, base: str, client: httpx.Client | None = None):
        self.base = base.rstrip("/")
        self.http = client or httpx.Client(timeout=30, headers={"Accept": "application/fhir+json"})

    def _check(self, response):
        if response.status_code >= 400:
            detail = response.text[:300]
            try:
                issues = response.json().get("issue", [])
                detail = "; ".join(issue.get("diagnostics", "") for issue in issues) or detail
            except ValueError:
                pass
            raise FhirError(response.status_code, detail)
        return response.json() if response.content else None

    def metadata(self):
        return self._check(self.http.get(f"{self.base}/metadata"))

    def read(self, kind: str, resource_id: str):
        return self._check(self.http.get(f"{self.base}/{kind}/{resource_id}"))

    def vread(self, kind: str, resource_id: str, version: str):
        return self._check(self.http.get(f"{self.base}/{kind}/{resource_id}/_history/{version}"))

    def history(self, kind: str, resource_id: str):
        """Every version, newest first. Uses vread per version: HAPI's instance
        _history search returned only the latest version here (search cache)."""
        current = self.read(kind, resource_id)
        latest = int(current["meta"]["versionId"])
        return [current, *(self.vread(kind, resource_id, str(version)) for version in range(latest - 1, 0, -1))]

    def put(self, resource: dict):
        url = f"{self.base}/{resource['resourceType']}/{resource['id']}"
        return self._check(self.http.put(url, json=resource, headers={"Content-Type": "application/fhir+json"}))

    def create(self, resource: dict):
        return self._check(self.http.post(f"{self.base}/{resource['resourceType']}", json=resource,
                                          headers={"Content-Type": "application/fhir+json"}))

    def transaction(self, resources: list):
        """All-or-nothing creation with client-assigned (opaque) IDs."""
        bundle = {"resourceType": "Bundle", "type": "transaction", "entry": [
            {"fullUrl": f"{item['resourceType']}/{item['id']}", "resource": item,
             "request": {"method": "PUT", "url": f"{item['resourceType']}/{item['id']}"}} for item in resources]}
        return self._check(self.http.post(self.base, json=bundle, headers={"Content-Type": "application/fhir+json"}))

    def search(self, kind: str, **params):
        params.setdefault("_count", "200")
        # HAPI reuses cached search results for ~60 s by default; lists must
        # show what was just written, so ask it not to.
        bundle = self._check(self.http.get(f"{self.base}/{kind}", params=params, headers={"Cache-Control": "no-cache"}))
        return [entry["resource"] for entry in bundle.get("entry", []) if "resource" in entry]
