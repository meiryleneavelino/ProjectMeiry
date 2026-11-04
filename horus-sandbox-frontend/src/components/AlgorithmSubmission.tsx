import { useEffect, useState } from "react";
import { FileCode2, LoaderCircle, Upload } from "lucide-react";
import { Link } from "react-router-dom";
import { governance, postGovernance } from "@/data/governance";
import type { Identity, Submission } from "@/types/governance";

const pendingStates = new Set(["drawing", "assigned"]);
const MAX_BYTES = 900 * 1024;
const stageLabel: Record<string, string> = {
  drawing: "Drawing the reviewer (commit-reveal between organizations)",
  assigned: "Analysis running in the reviewer's own environment",
  approved: "Approved", rejected: "Rejected", error: "Analysis failed",
};
const input = "w-full rounded-lg border border-line bg-white px-3 py-2 text-sm";

export default function AlgorithmSubmission({ organizations, identity, onCatalogChange }: {
  organizations: string[]; identity: Identity | null; onCatalogChange: () => void;
}) {
  const [mode, setMode] = useState("paste");
  const [code, setCode] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [item, setItem] = useState<Submission | null>(null);
  const [history, setHistory] = useState<{ code_hash: string; status: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const eligible = identity ? organizations.filter(organization => organization !== identity.organization) : [];
  const pending = item !== null && pendingStates.has(item.status);

  async function refreshHistory() {
    try { setHistory(await governance("/submissions")); } catch { setHistory([]); }
  }
  useEffect(() => { void refreshHistory(); }, []);
  useEffect(() => {
    if (!item || !pendingStates.has(item.status)) return;
    let disposed = false;
    let polling = false;
    const timer = window.setInterval(async () => {
      if (polling) return;
      polling = true;
      try {
        const updated = await governance<Submission>(`/submissions/${item.code_hash}`);
        if (!disposed) {
          setItem(updated);
          setError("");
          if (!pendingStates.has(updated.status)) {
            void refreshHistory();
            onCatalogChange();
          }
        }
      } catch (failure) {
        if (!disposed) setError(failure instanceof Error ? failure.message : "Analysis status unavailable");
      } finally { polling = false; }
    }, 1500);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [item?.code_hash, item?.status]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    if (mode === "file" && (!file || !/\.(py|txt)$/i.test(file.name))) return setError("Select a .py or .txt file.");
    if ((mode === "file" ? file!.size : new TextEncoder().encode(code).byteLength) > MAX_BYTES) return setError("Code must not exceed 900 KB.");
    setBusy(true);
    try {
      let submitted: Submission;
      if (mode === "file") {
        const data = new FormData();
        data.set("file", file!);
        data.set("organizations", JSON.stringify(organizations));
        submitted = await governance("/submissions", { method: "POST", body: data });
      } else submitted = await postGovernance("/submissions", { code, organizations });
      setItem(submitted);
      void refreshHistory();
      if (submitted.status === "approved") onCatalogChange();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Submission failed"); }
    finally { setBusy(false); }
  }

  return <section className="space-y-4 border-t border-line pt-5" aria-labelledby="validation-title">
    <h3 id="validation-title" className="flex items-center gap-2 font-serif text-lg font-semibold"><FileCode2 size={19} /> Algorithm validation</h3>
    <form onSubmit={submit} className="space-y-3">
      <fieldset disabled={busy || pending} className="space-y-3 disabled:opacity-60">
        <legend className="sr-only">Code submission</legend>
        <div className="flex gap-5 text-sm">
          <label className="flex items-center gap-2"><input type="radio" name="submission-mode" checked={mode === "paste"} onChange={() => setMode("paste")} /> Paste code</label>
          <label className="flex items-center gap-2"><input type="radio" name="submission-mode" checked={mode === "file"} onChange={() => setMode("file")} /> Upload file</label>
        </div>
        {mode === "paste" ? <label className="block space-y-1 text-sm">Python code
          <textarea aria-label="Python code" required rows={8} spellCheck={false} value={code} onChange={event => setCode(event.target.value)} className={`${input} font-mono`} />
        </label> : <label className="block space-y-1 text-sm">Script (.py or .txt)
          <input aria-label="Script file" type="file" accept=".py,.txt" required onChange={event => setFile(event.target.files?.[0] ?? null)} className={`${input} min-w-0`} />
        </label>}
      </fieldset>
      <div className="flex flex-wrap items-center gap-3">
        <button disabled={busy || pending || !eligible.length} className="flex items-center gap-2 rounded-lg border border-line px-4 py-2 text-sm font-semibold disabled:opacity-40">
          {busy || pending ? <LoaderCircle size={16} className="animate-spin" /> : <Upload size={16} />} Submit for validation
        </button>
        <span className="text-xs text-ink-muted">Eligible reviewers: {eligible.join(", ") || "None"} | Excluded: {identity?.organization ?? "Unavailable"}</span>
      </div>
    </form>
    {error && <p role="alert" className="break-words text-sm text-status-red">{error}</p>}
    {history.length > 0 && <label className="block space-y-1 text-sm">Previous submissions
      <select aria-label="Previous submissions" value={item?.code_hash ?? ""} className={input} onChange={event => {
        if (event.target.value) void governance<Submission>(`/submissions/${event.target.value}`).then(setItem).catch(failure => setError(failure.message));
      }}><option value="">Select a submission</option>{history.map(entry => <option key={entry.code_hash} value={entry.code_hash}>{entry.code_hash.slice(0, 16)} | {entry.status}</option>)}</select>
    </label>}
    {item && <div className="space-y-3 border-t border-line pt-4" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <strong>{stageLabel[item.status] ?? item.status}{item.reused ? " (existing ledger record reused)" : ""}</strong>
        <span>Reviewer: {item.selection.reviewer ?? "not drawn yet"} | Excluded: {item.selection.excluded}</span>
      </div>
      <ol className="space-y-1 text-xs text-ink-muted">
        <li>1. Submitted by {item.researcher_org} (certificate identity {item.researcher_id.slice(0, 12)}...)</li>
        <li>2. Draw: commits {item.selection.commits.join(", ") || "none"} / reveals {item.selection.reveals.join(", ") || "none"} of {item.selection.eligible.join(", ")}
          {item.selection.defaulted.length > 0 && <> | defaulted: {item.selection.defaulted.join(", ")}</>}</li>
        <li>3. Reviewer: {item.selection.reviewer ?? "pending"}{item.selection.selection_version && <> ({item.selection.selection_version})</>}</li>
        <li>4. Signed analysis: {item.provenance ? `${item.provenance.msp_id} at ${new Date(item.provenance.recorded_at).toLocaleString()}` : "pending"}</li>
        <li>5. Audits: {item.audits.length ? item.audits.map(audit => `${audit.organization} ${audit.match ? "matches" : "DIFFERS"}`).join(", ") : "none yet"}</li>
      </ol>
      {item.disputed && <p role="alert" className="text-sm font-semibold text-status-red">Disputed: an independent re-analysis produced a different report. The algorithm is not usable.</p>}
      <div className="space-y-2 text-xs">
        <div>Code hash <code className="block break-all">{item.code_hash}</code>
          {item.tx_ids.CodeSubmitted && <Link className="break-all text-violet-deep underline" to={`/ledger?code_hash=${item.code_hash}&tx_id=${item.tx_ids.CodeSubmitted}`}>Submission transaction: {item.tx_ids.CodeSubmitted}</Link>}</div>
        {item.report_hash && <div>Report hash <code className="block break-all">{item.report_hash}</code>
          <Link className="break-all text-violet-deep underline" to={`/ledger?code_hash=${item.code_hash}&tx_id=${item.tx_ids.CodeAnalyzed}`}>Analysis transaction: {item.tx_ids.CodeAnalyzed}</Link></div>}
      </div>
      {item.error && <p role="alert" className="text-sm text-status-red">{item.error}</p>}
      {item.report && <>
        <div className="flex flex-wrap gap-5 text-sm">
          <strong>Security score: {item.report.score}/100</strong>
          <span>High: {item.report.counts.high}</span><span>Medium: {item.report.counts.medium}</span><span>Low: {item.report.counts.low}</span>
          <strong className={item.report.decision === "approved" && !item.disputed ? "text-status-green" : "text-status-red"}>{item.report.decision.toUpperCase()}</strong>
        </div>
        <ul className="space-y-1 text-sm text-ink-muted">{item.report.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>
        <div className="overflow-x-auto"><table className="w-full min-w-[560px] text-left text-sm">
          <thead><tr className="border-b border-line"><th className="py-2">Rule</th><th>Line</th><th>Severity</th><th>Message</th></tr></thead>
          <tbody>{item.report.findings.map((finding, index) => <tr key={`${finding.rule_id}-${finding.line}-${index}`} className="border-b border-line">
            <td className="py-2 pr-3 font-mono text-xs">{finding.rule_id}</td><td className="pr-3">{finding.line}</td><td className="pr-3 capitalize">{finding.severity}</td><td>{finding.message}</td>
          </tr>)}</tbody>
        </table>{!item.report.findings.length && <p className="py-3 text-sm text-ink-muted">No findings under the current policy.</p>}</div>
        {item.provenance && <details className="text-xs"><summary className="cursor-pointer font-semibold">Analysis provenance</summary>
          <dl className="mt-2 space-y-2 break-all"><dt>Signed by</dt><dd>{item.provenance.organization} ({item.provenance.msp_id})</dd>
            <dt>Analyzer image digest</dt><dd>{item.provenance.image_digest}</dd>
            <dt>Draw seed</dt><dd>{item.selection.seed ?? "single eligible organization"}</dd>
            <dt>Rules hash</dt><dd>{item.report.rules_hash}</dd><dt>Policy hash</dt><dd>{item.report.policy_hash}</dd><dt>Semgrep</dt><dd>{item.report.semgrep_version}</dd></dl>
        </details>}
      </>}
    </div>}
  </section>;
}