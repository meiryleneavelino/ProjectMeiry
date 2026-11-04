import { CloudOff } from "lucide-react";

// Placeholder each FHIR screen shows instead of its content when the API is down.
export default function FhirUnavailable() {
  return (
    <div className="flex flex-col items-center gap-2 rounded-card border border-dashed border-line bg-white px-6 py-12 text-center text-ink-muted">
      <CloudOff size={28} className="text-ink-faint" />
      <div className="text-[15px] font-semibold text-ink">serviço FHIR indisponível</div>
      <div className="max-w-md text-[13px]">
        Esta tela depende só da API do PEP (horus-fhir). O restante do Horus continua funcionando normalmente.
      </div>
    </div>
  );
}
