import { useEffect, useState } from "react";
import { Download, LoaderCircle, Play, RefreshCw, ShieldCheck, Square } from "lucide-react";
import AlgorithmSubmission from "@/components/AlgorithmSubmission";
import { governance, postGovernance } from "@/data/governance";
import type { Algorithm, Identity } from "@/types/governance";

type Catalog = {
  organizations: string[];
  algorithms: { id: string; name: string }[];
  dataset_id: string;
  network_verified: boolean;
};
type Observation = {
  organization: string;
  job: string;
  namespace: string;
  accuracy: number;
  validation_loss: number;
};
type Run = {
  id: string;
  status: string;
  organizations: string[];
  rounds: number;
  completed_rounds: number;
  error?: string;
  round_history: { round: number; organizations: Observation[] }[];
};
const terminalStates = new Set(["completed", "failed", "cancelled", "interrupted"]);
const inputStyle = "w-full rounded-lg border border-line bg-white px-3 py-2 text-sm";

async function api<Result>(path: string, payload?: object): Promise<Result> {
  const response = await fetch(`/training-api${path}`, {
    method: payload ? "POST" : "GET",
    headers: payload ? { "Content-Type": "application/json" } : undefined,
    body: payload ? JSON.stringify(payload) : undefined,
    signal: AbortSignal.timeout(10000),
  });
  if (!response.ok) {
    const result = await response.json().catch(() => null);
    throw new Error(typeof result?.detail === "string" ? result.detail : `API error (${response.status})`);
  }
  return response.json();
}

export default function FederatedTraining() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [organizations, setOrganizations] = useState(["UVA", "VU", "TUDELFT"]);
  const [algorithm, setAlgorithm] = useState("logistic-regression-v1");
  const [rounds, setRounds] = useState(3);
  const [epochs, setEpochs] = useState(2);
  const [run, setRun] = useState<Run | null>(null);
  const [history, setHistory] = useState<Run[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [algorithms, setAlgorithms] = useState<Algorithm[]>([]);
  const [governanceError, setGovernanceError] = useState("");
  const [requestKey, setRequestKey] = useState<string | null>(null);
  const selectedAlgorithm = algorithms.find(item => item.id === algorithm);
  const active = run !== null && !terminalStates.has(run.status);

  async function refreshGovernance() {
    try {
      const [person, catalog] = await Promise.all([governance<Identity>("/me"), governance<Algorithm[]>("/algorithms")]);
      setIdentity(person);
      setAlgorithms(catalog);
      setGovernanceError("");
    } catch (failure) { setGovernanceError(failure instanceof Error ? failure.message : "Governance unavailable"); }
  }

  async function refresh() {
    try {
      const [nextCatalog, nextHistory] = await Promise.all([api<Catalog>("/catalog"), api<Run[]>("/runs")]);
      setCatalog(nextCatalog);
      setHistory(nextHistory);
      setRun((current) => current ? nextHistory.find((item) => item.id === current.id) ?? current : nextHistory[0] ?? null);
      setError("");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Training API unavailable");
    }
  }

  useEffect(() => {
    void refresh();
    void refreshGovernance();
  }, []);

  useEffect(() => {
    if (!run || terminalStates.has(run.status)) return;
    const runId = run.id;
    let disposed = false;
    let polling = false;
    const interval = window.setInterval(async () => {
      if (polling) return;
      polling = true;
      try {
        const updated = await api<Run>(`/runs/${runId}`);
        if (!disposed) {
          setRun(updated);
          setHistory((current) => current.map((item) => item.id === updated.id ? updated : item));
          setError("");
        }
      } catch (failure) {
        if (!disposed) setError(failure instanceof Error ? failure.message : "Status unavailable");
      } finally {
        polling = false;
      }
    }, 2000);
    return () => { disposed = true; window.clearInterval(interval); };
  }, [run?.id, run?.status]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const key = requestKey ?? crypto.randomUUID();
      setRequestKey(key);
      const created = await postGovernance<Run>("/training/runs", {
        algorithm, organizations, dataset_id: catalog?.dataset_id,
        rounds, local_epochs: epochs,
      }, { "Idempotency-Key": key });
      setRun(created);
      setHistory((current) => [created, ...current]);
      setRequestKey(null);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not start training");
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!run) return;
    setBusy(true);
    try {
      setRun(await api<Run>(`/runs/${run.id}/cancel`, {}));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not cancel training");
    } finally {
      setBusy(false);
    }
  }

  async function download() {
    if (!run || run.status !== "completed") return;
    setDownloading(true);
    try {
      const response = await fetch(`/training-api/runs/${run.id}/model`, { signal: AbortSignal.timeout(10000) });
      if (!response.ok) throw new Error("Final model unavailable");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `global-model-${run.id}.json`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Download failed");
    } finally {
      setDownloading(false);
    }
  }

  const observations = run?.round_history.slice(-1)[0]?.organizations ?? [];
  return (
    <div className="max-w-5xl space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-4">
        <h2 className="font-serif text-xl font-semibold">Federated training</h2>
        <div className="flex items-center gap-3">
          <span className={`flex items-center gap-1.5 text-xs ${catalog?.network_verified ? "text-status-green" : "text-status-red"}`}>
            <ShieldCheck size={16} /> Isolation: {catalog?.network_verified ? "verified" : "unverified"}
          </span>
          <button type="button" onClick={() => void refresh()} title="Refresh training status" aria-label="Refresh training status"
            className="flex h-9 w-9 items-center justify-center rounded-lg border border-line"><RefreshCw size={17} /></button>
        </div>
      </header>
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <span>Researcher: <strong>{identity?.name ?? "Unavailable"}</strong></span>
        <span>Organization: <strong>{identity?.organization === "TUDELFT" ? "TUDelft" : identity?.organization ?? "Unavailable"}</strong></span>
      </div>
      {governanceError && <p role="alert" className="text-sm text-status-red">{governanceError}</p>}
      {error && <div role="alert" className="rounded-lg border border-status-red p-3 text-sm text-status-red">{error}</div>}
      <form onSubmit={submit} className="space-y-5">
        <fieldset disabled={busy || active} className="space-y-5 disabled:opacity-60">
          <legend className="mb-3 text-sm font-semibold">Organizations</legend>
          <div className="flex flex-wrap gap-5">
            {(catalog?.organizations ?? ["UVA", "VU", "TUDELFT"]).map((organization) => (
              <label key={organization} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={organizations.includes(organization)} onChange={(event) => setOrganizations((current) =>
                  event.target.checked ? [...current, organization] : current.filter((item) => item !== organization))} />
                {organization === "TUDELFT" ? "TUDelft" : organization}
              </label>
            ))}
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <label className="space-y-1 text-sm">Algorithm<select aria-label="Algorithm" value={algorithm} onChange={(event) => setAlgorithm(event.target.value)} className={inputStyle}>
              {!algorithms.length && <option value="">Catalog unavailable</option>}
              {algorithms.map((item) => <option key={item.id} value={item.id}>{item.name} | {item.score}/100{item.executable ? "" : " | Catalog only"}</option>)}
            </select></label>
            <label className="space-y-1 text-sm">Dataset<select aria-label="Dataset" className={inputStyle} value="synthetic-local-v1" disabled><option value="synthetic-local-v1">Synthetic local v1</option></select></label>
            <label className="space-y-1 text-sm">Federated rounds<input aria-label="Federated rounds" type="number" min={1} max={10} required value={rounds} onChange={(event) => setRounds(Number(event.target.value))} className={inputStyle} /></label>
            <label className="space-y-1 text-sm">Local epochs<input aria-label="Local epochs" type="number" min={1} max={5} required value={epochs} onChange={(event) => setEpochs(Number(event.target.value))} className={inputStyle} /></label>
          </div>
        </fieldset>
        <div className="flex flex-wrap gap-3">
          <button type="submit" disabled={!catalog?.network_verified || !selectedAlgorithm?.executable || !identity || organizations.length < 2 || busy || active}
            className="flex items-center gap-2 rounded-lg bg-violet-deep px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">
            {busy ? <LoaderCircle size={16} className="animate-spin" /> : <Play size={16} />} Start training
          </button>
          {active && <button type="button" onClick={() => void cancel()} disabled={busy || run?.status === "cancelling"}
            className="flex items-center gap-2 rounded-lg border border-line px-4 py-2 text-sm disabled:opacity-40"><Square size={16} /> Cancel</button>}
        </div>
        {selectedAlgorithm && <p className="text-xs text-ink-muted">Security score: {selectedAlgorithm.score}/100 | Validation: {selectedAlgorithm.validation_source === "builtin-trusted" ? "Trusted built-in baseline" : "Semgrep"}</p>}
        {selectedAlgorithm && !selectedAlgorithm.executable && <p role="status" className="text-sm text-status-red">Validated and registered. Execution of submitted algorithms awaits the sandbox phase.</p>}
        {requestKey && !busy && <p className="break-all text-xs text-ink-muted">Training request: {requestKey}. Check execution history before retrying an uncertain request.</p>}
      </form>
      <AlgorithmSubmission organizations={organizations} identity={identity} onCatalogChange={() => void refreshGovernance()} />
      {run && <section className="space-y-4 border-t border-line pt-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><h3 className="font-serif text-lg font-semibold">Global model</h3>
            <p role="status" className="text-sm capitalize">{run.status} | Round {run.completed_rounds} / {run.rounds}</p></div>
          <button type="button" disabled={run.status !== "completed" || downloading} onClick={() => void download()}
            className="flex items-center gap-2 rounded-lg border border-line px-4 py-2 text-sm font-semibold disabled:opacity-40">
            <Download size={16} /> Download final model
          </button>
        </div>
        <progress aria-label="Training progress" className="h-2 w-full" value={run.completed_rounds} max={run.rounds} />
        <p className="break-all text-xs text-ink-faint">{run.id}</p>
        {run.error && <p role="alert" className="text-sm text-status-red">{run.error}</p>}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[430px] text-left text-sm">
            <thead><tr className="border-b border-line text-ink-muted"><th className="py-2">Organization</th><th>Namespace</th><th>Local accuracy</th><th>Local validation loss</th></tr></thead>
            <tbody>{run.organizations.map((organization) => {
              const observation = observations.find((item) => item.organization === organization);
              return <tr key={organization} className="border-b border-line"><td className="py-3 font-semibold">{organization === "TUDELFT" ? "TUDelft" : organization}</td>
                <td>{organization.toLowerCase()}</td><td>{observation ? `${(observation.accuracy * 100).toFixed(1)}%` : "Pending"}</td>
                <td>{observation ? observation.validation_loss.toFixed(4) : "Pending"}</td></tr>;
            })}</tbody>
          </table>
        </div>
      </section>}
      {history.length > 1 && <section className="border-t border-line pt-5">
        <label className="block max-w-xl space-y-2 text-sm font-semibold">Execution history
          <select className={inputStyle} value={run?.id ?? ""} onChange={(event) => setRun(history.find((item) => item.id === event.target.value) ?? null)}>
            {history.map((item) => <option key={item.id} value={item.id}>{item.status} | {item.id}</option>)}
          </select>
        </label>
      </section>}
    </div>
  );
}