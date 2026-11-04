import { Routes, Route } from "react-router-dom";
import Sidebar from "@/components/Sidebar";
import Topbar from "@/components/Topbar";
import Dashboard from "@/pages/Dashboard";
import NewJob from "@/pages/NewJob";
import Jobs from "@/pages/Jobs";
import Authorizations from "@/pages/Authorizations";
import Ledger from "@/pages/Ledger";
import Models from "@/pages/Models";
import Datasets from "@/pages/Datasets";
import Security from "@/pages/Security";
import Reports from "@/pages/Reports";
import Settings from "@/pages/Settings";
import FederatedTraining from "@/pages/FederatedTraining";
import FhirLayout from "@/components/fhir/FhirLayout";
import FhirConsent from "@/pages/fhir/Consent";
import FhirLab from "@/pages/fhir/Lab";
import FhirAccess from "@/pages/fhir/Access";
import FhirPolicies from "@/pages/fhir/Policies";
import FhirAudit from "@/pages/fhir/Audit";

export default function App() {
  return (
    <div className="grid min-h-screen grid-cols-1 md:grid-cols-[250px_1fr]">
      <Sidebar />
      <div className="min-w-0">
        <Topbar
          title="Federated Learning Sandbox"
          subtitle="Governed Federated Blind TRE"
        />
        <main className="mx-auto max-w-[1400px] px-4 pb-16 pt-6 md:px-7">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/new-job" element={<NewJob />} />
            <Route path="/training" element={<FederatedTraining />} />
            {/* Prontuário (FHIR): separate module and ledger (Fabric fhir-channel) */}
            <Route path="/fhir" element={<FhirLayout />}>
              <Route index element={<FhirAccess />} />
              <Route path="consent" element={<FhirConsent />} />
              <Route path="lab" element={<FhirLab />} />
              <Route path="access" element={<FhirAccess />} />
              <Route path="policies" element={<FhirPolicies />} />
              <Route path="audit" element={<FhirAudit />} />
            </Route>
            <Route path="/jobs" element={<Jobs />} />
            <Route path="/authorizations" element={<Authorizations />} />
            <Route path="/ledger" element={<Ledger />} />
            <Route path="/models" element={<Models />} />
            <Route path="/data" element={<Datasets />} />
            <Route path="/security" element={<Security />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
