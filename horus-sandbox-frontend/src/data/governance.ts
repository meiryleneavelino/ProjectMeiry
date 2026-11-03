export async function governance<Result>(path: string, options: RequestInit = {}): Promise<Result> {
  const response = await fetch(`/governance-api${path}`, {
    ...options, signal: options.signal ?? AbortSignal.timeout(90000),
  });
  const result = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof result?.detail === "string" ? result.detail : `Governance API error (${response.status})`);
  return result;
}

export function postGovernance<Result>(path: string, value?: object, headers?: Record<string, string>) {
  return governance<Result>(path, { method: "POST", headers: { "Content-Type": "application/json", ...headers },
    body: value === undefined ? undefined : JSON.stringify(value) });
}