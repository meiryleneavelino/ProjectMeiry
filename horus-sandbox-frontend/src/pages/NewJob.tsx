import { useState } from "react";
import { Check, X } from "lucide-react";
import Panel from "@/components/Panel";

// Ex-ante checklist: in production, each item comes from a
// "simulate()" call to the PDPSC (read-only, no transaction written) — see the
// discussion about PIP/PDP/PEP for the full design of this flow.
const preflightChecks = [
  { label: "Role allows this model", passed: true },
  { label: "Selected dataset is compatible", passed: true },
  { label: "Container image signed (Cosign)", passed: true },
  { label: "MFA enabled on account", passed: false },
];

export default function NewJob() {
  const [dataset, setDataset] = useState("south_region_sales.csv");
  const allPassed = preflightChecks.every((c) => c.passed);

  return (
    <div className="max-w-2xl">
      <h2 className="mb-1 font-serif text-xl font-semibold">New training job</h2>
      <p className="mb-5 text-sm text-ink-faint">
        Choose a model from the catalog, associate a local dataset, and review the checklist before
        submitting.
      </p>

      <Panel title="Configure training">
        <label className="mb-1 block text-[13px] font-semibold text-ink-muted">
          Local dataset
        </label>
        <select
          value={dataset}
          onChange={(e) => setDataset(e.target.value)}
          className="mb-4 w-full rounded-lg border border-line px-3 py-2 text-sm"
        >
          <option>south_region_sales.csv</option>
          <option>cardiology_records.fhir</option>
        </select>

        <label className="mb-1 block text-[13px] font-semibold text-ink-muted">
          Project purpose
        </label>
        <select className="mb-5 w-full rounded-lg border border-line px-3 py-2 text-sm">
          <option>Research project 123</option>
        </select>

        <div className="mb-5 rounded-lg bg-paper p-3.5">
          <p className="mb-2 text-xs font-semibold text-ink-faint">Preflight</p>
          {preflightChecks.map((c) => (
            <div key={c.label} className="mb-1.5 flex items-center gap-2 text-[13px] last:mb-0">
              {c.passed ? (
                <Check size={15} className="text-status-green" />
              ) : (
                <X size={15} className="text-status-red" />
              )}
              {c.label}
            </div>
          ))}
        </div>

        <button
          disabled={!allPassed}
          className="w-full rounded-lg bg-violet-deep py-2.5 text-sm font-bold text-white disabled:cursor-not-allowed disabled:opacity-40"
          title={!allPassed ? "Enable MFA to allow submission" : undefined}
        >
          Submit training job
        </button>
      </Panel>
    </div>
  );
}
