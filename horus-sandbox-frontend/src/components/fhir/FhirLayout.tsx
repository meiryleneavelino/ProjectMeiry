import { useCallback, useEffect, useState } from "react";
import { Outlet, useOutletContext } from "react-router-dom";
import { Link2, UserRound } from "lucide-react";
import { fhirApi, FhirUnavailable } from "@/data/fhir";
import type { FhirStatus, Persona, PersonaCatalog } from "@/types/fhir";

export interface FhirContext {
  persona: Persona | null;
  personas: Persona[];
  exams: PersonaCatalog["exams"];
  status: FhirStatus | null;
  unavailable: boolean;
  refresh: () => void;
  markUnavailable: () => void;
}

export const useFhir = () => useOutletContext<FhirContext>();

const STORAGE_KEY = "horus-fhir-persona";
const ROLE_LABEL: Record<Persona["role"], string> = { admin: "admin", patient: "paciente", physician: "médico(a)", lab: "laboratório" };

function readStored() {
  try { return localStorage.getItem(STORAGE_KEY) ?? "phy-001"; } catch { return "phy-001"; }
}

// Shared frame of every FHIR screen: persona selector, ledger label and the
// "service unavailable" state. Nothing here touches the sandbox APIs.
export default function FhirLayout() {
  const [catalog, setCatalog] = useState<PersonaCatalog | null>(null);
  const [status, setStatus] = useState<FhirStatus | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [personaId, setPersonaId] = useState(readStored);

  const refresh = useCallback(() => {
    Promise.all([fhirApi<PersonaCatalog>("/personas"), fhirApi<FhirStatus>("/status")])
      .then(([personas, current]) => { setCatalog(personas); setStatus(current); setUnavailable(false); })
      .catch(failure => { if (failure instanceof FhirUnavailable) setUnavailable(true); });
  }, []);

  useEffect(() => { refresh(); }, [refresh]);
  const markUnavailable = useCallback(() => setUnavailable(true), []);

  const choose = (id: string) => {
    setPersonaId(id);
    try { localStorage.setItem(STORAGE_KEY, id); } catch { /* per-browser convenience only */ }
  };

  const personas = catalog?.personas ?? [];
  const persona = personas.find(item => item.id === personaId) ?? null;
  const context: FhirContext = { persona, personas, exams: catalog?.exams ?? {}, status, unavailable, refresh,
    markUnavailable };

  return (
    <div>
      <div className="mb-4.5 flex flex-wrap items-center gap-3 rounded-card border border-line bg-white px-4 py-3">
        <div className="flex items-center gap-2 text-[13px] font-semibold text-ink">
          <UserRound size={16} className="text-violet-deep" /> Persona
        </div>
        <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Persona">
          {personas.map(item => (
            <button key={item.id} role="radio" aria-checked={item.id === personaId} onClick={() => choose(item.id)}
              className={["rounded-full border px-3 py-1 text-[12.5px] font-medium transition-colors",
                item.id === personaId ? "border-violet-deep bg-violet-deep text-white" : "border-line text-ink-muted hover:border-violet"].join(" ")}>
              {item.label}
            </button>
          ))}
          {!personas.length && <span className="text-[12.5px] text-ink-faint">—</span>}
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-3 text-[11.5px] text-ink-faint">
          {persona && <span>{persona.id} · {ROLE_LABEL[persona.role]} · {persona.msp}</span>}
          <span className="rounded bg-status-blueSoft px-1.5 py-0.5 text-status-blue">identidade simulada (?as=), não é autenticação</span>
          <span className="flex items-center gap-1"><Link2 size={12} /> Ledger: Fabric fhir-channel
            {status?.chain.ok && <> · altura {status.chain.height}</>}</span>
        </div>
      </div>
      {unavailable && (
        <div role="alert" className="mb-4.5 rounded-card border border-status-red/40 bg-status-redSoft px-4 py-3 text-sm text-status-red">
          <b>serviço FHIR indisponível.</b> A API do PEP (127.0.0.1:8099) não respondeu. As telas da sandbox não são afetadas.
          Para subir: <code>python3 horus-fhir/tools.py start</code>.{" "}
          <button className="underline" onClick={refresh}>Tentar de novo</button>
        </div>
      )}
      <Outlet context={context} />
    </div>
  );
}
