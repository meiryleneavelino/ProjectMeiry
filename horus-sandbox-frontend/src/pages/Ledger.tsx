import { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, Eye, FileCheck2, RefreshCw, Search, ShieldCheck } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { governance, postGovernance } from "@/data/governance";
import type { LedgerPage, LedgerTransaction } from "@/types/governance";

const eventTypes = ["ConfigInitialized", "CodeSubmitted", "SeedCommitted", "SeedRevealed", "DrawForced", "ReviewerSelected",
  "CodeAnalyzed", "CodeValidated", "CodeRejected", "AlgorithmRegistered", "AnalysisFailed", "AnalysisAudited", "TrainingStarted"];
const input = "w-full rounded-lg border border-line bg-white px-3 py-2 text-sm";

export default function Ledger() {
  const [params, setParams] = useSearchParams();
  const query = params.toString();
  const [code, setCode] = useState(params.get("code_hash") ?? "");
  const [eventType, setEventType] = useState(params.get("event_type") ?? "");
  const [page, setPage] = useState(0);
  const [data, setData] = useState<LedgerPage | null>(null);
  const [selected, setSelected] = useState<LedgerTransaction | null>(null);
  const [error, setError] = useState("");
  const [verification, setVerification] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);

  function openTransaction(txId: string) {
    void governance<LedgerTransaction>(`/ledger/transactions/${encodeURIComponent(txId)}`)
      .then(result => { setSelected(result); setError(""); }).catch(failure => setError(failure.message));
  }

  useEffect(() => {
    let disposed = false;
    setCode(params.get("code_hash") ?? "");
    setEventType(params.get("event_type") ?? "");
    const filter = new URLSearchParams({ offset: String(page * 20), limit: "20" });
    if (params.get("code_hash")) filter.set("code_hash", params.get("code_hash")!);
    if (params.get("event_type")) filter.set("event_type", params.get("event_type")!);
    setBusy(true);
    void governance<LedgerPage>(`/ledger/events?${filter}`).then(result => {
      if (!disposed) { setData(result); setError(""); }
    }).catch(failure => { if (!disposed) { setData(null); setError(failure.message); } })
      .finally(() => { if (!disposed) setBusy(false); });
    const transaction = params.get("tx_id");
    if (transaction) void governance<LedgerTransaction>(`/ledger/transactions/${encodeURIComponent(transaction)}`)
      .then(result => { if (!disposed) setSelected(result); }).catch(failure => { if (!disposed) setError(failure.message); });
    return () => { disposed = true; };
  }, [query, page, revision]);

  const selectedCode = selected?.events.find(event => event.code_hash)?.code_hash ?? "";
  const reportHash = code.trim() || selectedCode;

  async function verify(report: boolean) {
    setBusy(true);
    setVerification(null);
    try {
      setVerification(await postGovernance<Record<string, unknown>>(report ? `/reports/${reportHash}/verify` : "/ledger/verify"));
      setError("");
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Verification failed"); }
    finally { setBusy(false); }
  }

  return <div className="max-w-6xl space-y-5">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-4">
      <div><h2 className="font-serif text-xl font-semibold">Ledger (events)</h2>
        <p className="text-xs text-ink-muted">Hyperledger Fabric channel horus-governance | replicated on the UVA, VU and TUDELFT peers</p></div>
      <div className="flex flex-wrap gap-2">
        <button onClick={() => void verify(false)} disabled={busy} className="flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-sm disabled:opacity-40"><ShieldCheck size={16} /> Chain head</button>
        <button onClick={() => void verify(true)} disabled={busy || !/^[0-9a-f]{64}$/.test(reportHash)} className="flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-sm disabled:opacity-40"><FileCheck2 size={16} /> Verify report</button>
        <button onClick={() => setRevision(value => value + 1)} title="Refresh events" aria-label="Refresh events" className="flex h-9 w-9 items-center justify-center rounded-lg border border-line"><RefreshCw size={17} /></button>
      </div>
    </header>
    <form className="grid items-end gap-3 sm:grid-cols-[minmax(0,1fr)_220px_auto]" onSubmit={event => {
      event.preventDefault();
      setPage(0); setSelected(null); setVerification(null);
      const next = new URLSearchParams();
      if (code.trim()) next.set("code_hash", code.trim());
      if (eventType) next.set("event_type", eventType);
      setParams(next);
      setRevision(value => value + 1);
    }}>
      <label className="min-w-0 space-y-1 text-sm">Code hash<input aria-label="Code hash" value={code} onChange={event => setCode(event.target.value)} className={`${input} font-mono`} placeholder="SHA-256" /></label>
      <label className="space-y-1 text-sm">Event type<select aria-label="Event type" value={eventType} onChange={event => setEventType(event.target.value)} className={input}><option value="">All events</option>{eventTypes.map(type => <option key={type}>{type}</option>)}</select></label>
      <button className="flex items-center justify-center gap-2 rounded-lg bg-violet-deep px-4 py-2 text-sm font-semibold text-white"><Search size={16} /> Search</button>
    </form>
    {error && <p role="alert" className="break-words text-sm text-status-red">{error}</p>}
    {verification && <section className="space-y-2 border-y border-line py-3" aria-live="polite">
      <strong className={verification.valid ? "text-status-green" : "text-status-red"}>{verification.valid ? "Verification passed" : "Verification failed"}</strong>
      <pre className="overflow-x-auto text-xs">{JSON.stringify(verification, null, 2)}</pre>
    </section>}
    <div className="relative min-w-0 overflow-x-auto"><table className="w-full min-w-[760px] text-left text-sm">
      <thead><tr className="border-b border-line text-ink-muted"><th className="py-2">Recorded at</th><th>Event</th><th>Signed by</th><th>Code hash</th><th>Transaction</th><th><span className="sr-only">Details</span></th></tr></thead>
      <tbody>{data?.items.map(record => <tr key={`${record.tx_id}-${record.event_type}`} className="border-b border-line">
        <td className="py-3 pr-4 text-xs">{new Date(record.recorded_at).toLocaleString()}</td><td className="pr-4 font-semibold">{record.event_type}</td>
        <td className="pr-4 text-xs">{record.organization || "-"} <span className="text-ink-muted">({record.msp_id || "-"})</span></td>
        <td className="pr-4 font-mono text-xs">{record.code_hash ? `${record.code_hash.slice(0, 12)}...` : "-"}</td>
        <td className="font-mono text-xs">{record.tx_id.slice(0, 16)}...</td>
        <td><button onClick={() => openTransaction(record.tx_id)} aria-label={`View transaction ${record.tx_id}`} title="View transaction details" className="flex h-9 w-9 items-center justify-center rounded-lg border border-line"><Eye size={16} /></button></td>
      </tr>)}</tbody>
    </table>{data?.total === 0 && <p className="py-5 text-sm text-ink-muted">No matching events.</p>}</div>
    <div className="flex items-center justify-between gap-3 text-sm">
      <span>{busy ? "Loading..." : `${data?.total ?? 0} events | Page ${page + 1}`}</span>
      <div className="flex gap-2"><button title="Previous page" aria-label="Previous page" disabled={busy || page === 0} onClick={() => setPage(value => value - 1)} className="flex h-9 w-9 items-center justify-center rounded-lg border border-line disabled:opacity-40"><ArrowLeft size={16} /></button>
        <button title="Next page" aria-label="Next page" disabled={busy || (page + 1) * 20 >= (data?.total ?? 0)} onClick={() => setPage(value => value + 1)} className="flex h-9 w-9 items-center justify-center rounded-lg border border-line disabled:opacity-40"><ArrowRight size={16} /></button></div>
    </div>
    {selected && <section className="space-y-3 border-t border-line pt-4" aria-label="Transaction details">
      <h3 className="font-serif text-lg font-semibold">Transaction {selected.tx_id.slice(0, 16)}...</h3>
      <dl className="grid gap-2 text-xs sm:grid-cols-[140px_minmax(0,1fr)]">
        <dt>Transaction ID</dt><dd className="break-all font-mono">{selected.tx_id}</dd>
        <dt>Block number</dt><dd className="font-mono">{selected.block_number ?? "-"}</dd>
        <dt>Validation</dt><dd className={selected.valid ? "text-status-green" : "text-status-red"}>{selected.validation_code}</dd>
        <dt>Block data hash</dt><dd className="break-all font-mono">{selected.block_data_hash ?? "-"}</dd>
      </dl>
      {selected.events.map(event => <div key={event.event_type} className="space-y-1">
        <p className="text-sm font-semibold">{event.event_type} <span className="font-normal text-ink-muted">by {event.organization || "-"} ({event.msp_id || "-"})</span></p>
        <pre className="overflow-x-auto border-l-2 border-line py-2 pl-3 text-xs">{JSON.stringify(event.payload, null, 2)}</pre>
      </div>)}
    </section>}
  </div>;
}
