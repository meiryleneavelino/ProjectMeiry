import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { errorText, fhirApi, FhirUnavailable } from "@/data/fhir";
import { useFhir } from "@/components/fhir/FhirLayout";
import type { Persona } from "@/types/fhir";

export const input = "w-full rounded-lg border border-line bg-white px-3 py-2 text-sm";
export const primary = "flex items-center justify-center gap-2 rounded-lg bg-violet-deep px-4 py-2 text-sm font-semibold text-white disabled:opacity-40";
export const secondary = "flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1.5 text-[12.5px] disabled:opacity-40";

// Loads one /fhir-api path; flags the whole FHIR area unavailable if the API is down.
export function useFhirData<T>(path: string) {
  const { markUnavailable, unavailable } = useFhir();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const reload = useCallback(() => {
    fhirApi<T>(path).then(result => { setData(result); setError(""); }).catch(failure => {
      if (failure instanceof FhirUnavailable) markUnavailable();
      else setError(errorText(failure));
    });
  }, [path, markUnavailable]);
  useEffect(() => { if (!unavailable) reload(); }, [reload, unavailable]);
  return { data, error, reload };
}

// Wraps a write: busy flag, error text, unavailable handling.
export function useAction() {
  const { markUnavailable, refresh } = useFhir();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = async <T,>(action: () => Promise<T>): Promise<T | null> => {
    setBusy(true);
    setError("");
    try {
      const result = await action();
      refresh();
      return result;
    } catch (failure) {
      if (failure instanceof FhirUnavailable) markUnavailable();
      setError(errorText(failure));
      return null;
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run, setError };
}

export function RoleHint({ persona, expected, who }: { persona: Persona | null; expected: Persona["role"]; who: string }) {
  if (!persona || persona.role === expected) return null;
  return (
    <div className="mb-3 rounded-lg bg-[#fff6e5] px-3 py-2 text-[12.5px] text-[#8a5a00]">
      Esta ação é de {who}. Com a persona <b>{persona.label}</b> o envio continua permitido para você ver a recusa vinda do chaincode.
    </div>
  );
}

export function ErrorLine({ text }: { text: string }) {
  return text ? <div role="alert" className="mt-2 text-[12.5px] text-status-red">{text}</div> : null;
}

export function TxLine({ txId, block, children }: { txId?: string | null; block?: number | null; children?: ReactNode }) {
  return (
    <div className="font-mono text-[11px] text-ink-faint">
      {children} tx {txId ? `${txId.slice(0, 16)}…` : "—"} · bloco {block ?? "—"}
    </div>
  );
}

export function PageTitle({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="mb-4">
      <h2 className="m-0 font-serif text-[22px] font-semibold text-ink">{title}</h2>
      <div className="mt-0.5 text-[13px] text-ink-muted">{subtitle}</div>
    </div>
  );
}
