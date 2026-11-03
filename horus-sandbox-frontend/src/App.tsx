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
