// Client of the horus-fhir PEP API. The browser calls /fhir-api; the Vite
// proxy adds the token server-side. FHIR itself is never reachable from here.

export class FhirUnavailable extends Error {
  constructor() {
    super("serviço FHIR indisponível");
  }
}

export class FhirApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

export async function fhirApi<Result>(path: string, options: RequestInit = {}): Promise<Result> {
  let response: Response;
  try {
    response = await fetch(`/fhir-api${path}`, { ...options, signal: options.signal ?? AbortSignal.timeout(120000) });
  } catch (failure) {
    if (failure instanceof DOMException && failure.name === "AbortError") throw failure;
    throw new FhirUnavailable();
  }
  const body = await response.json().catch(() => null);
  // The Vite proxy answers 5xx without a JSON body when fhir-api is down.
  if (!body && response.status >= 500) throw new FhirUnavailable();
  if (!response.ok && response.status !== 403) {
    const detail = typeof body?.detail === "string" ? body.detail : `FHIR API error (${response.status})`;
    throw new FhirApiError(response.status, detail, body);
  }
  if (response.status === 403 && !("permitted" in (body ?? {}))) {
    throw new FhirApiError(403, typeof body?.detail === "string" ? body.detail : "negado", body);
  }
  return body as Result;
}

export function postFhir<Result>(path: string, value: object = {}) {
  return fhirApi<Result>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value) });
}

export const shortHash = (value?: string | null, size = 12) => (value ? `${value.slice(0, size)}…` : "—");

export const formatDate = (value?: string | null) =>
  value ? new Date(value).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "medium" }) : "—";

export const errorText = (failure: unknown) => (failure instanceof Error ? failure.message : "Falha inesperada");
