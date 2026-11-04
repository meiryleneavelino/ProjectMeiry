import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, Clock, XCircle, Boxes, ShieldCheck } from "lucide-react";
import StatCard from "@/components/StatCard";
import Panel from "@/components/Panel";
import JobsTable from "@/components/JobsTable";
import SandboxStatusPanel from "@/components/SandboxStatusPanel";
import AuthorizationsPanel from "@/components/AuthorizationsPanel";
import UsageChart from "@/components/charts/UsageChart";
import ModelDistributionChart from "@/components/charts/ModelDistributionChart";
import {
  mockJobs,
  mockAuthorizations,
  mockSandboxStatus,
  mockModelUsage,
  mockResourceUsage,
} from "@/data/mock";
import type { JobStatus } from "@/types";
import type { GovernanceStatus, LedgerEvent, LedgerPage } from "@/types/governance";
import { governance } from "@/data/governance";

type Filter = "all" | JobStatus;

export default function Dashboard() {
  const [filter, setFilter] = useState<Filter>("all");
  const [governanceStatus, setGovernanceStatus] = useState<GovernanceStatus | null>(null);
  const [ledgerEvents, setLedgerEvents] = useState<LedgerEvent[]>([]);
  useEffect(() => {
    let disposed = false;
    async function refresh() {
      try {
        const [status, events] = await Promise.all([governance<GovernanceStatus>("/status"), governance<LedgerPage>("/ledger/events?limit=5")]);
        if (!disposed) { setGovernanceStatus(status); setLedgerEvents(events.items); }
      } catch { if (!disposed) { setGovernanceStatus(null); setLedgerEvents([]); } }
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 10000);
    return () => { disposed = true; window.clearInterval(timer); };
  }, []);
  const statusItems = [
    { label: "Ledger (Hyperledger Fabric)", value: governanceStatus?.ledger.valid ? `Reachable | ${governanceStatus.ledger.height ?? 0} blocks` : "Unavailable", healthy: governanceStatus?.ledger.valid ?? false },
    { label: "SAST analysis", value: "Organization-local agents (UVA, VU, TUDELFT)", healthy: governanceStatus?.ledger_ready ?? false },
    ...mockSandboxStatus.filter(item => !item.label.startsWith("Ledger")).map(item => ({ ...item, value: `${item.value} (demo)`, healthy: false })),
  ];

  const visibleJobs = useMemo(
    () => (filter === "all" ? mockJobs : mockJobs.filter((j) => j.status === filter)),
    [filter]
  );

  const counts = useMemo(
    () => ({
      authorized: mockJobs.filter((j) => j.status === "authorized" || j.status === "done").length,
      running: mockJobs.filter((j) => j.status === "running").length,
      denied: mockJobs.filter((j) => j.status === "denied").length,
      released: mockJobs.filter((j) => j.status === "done").length,
    }),
    []
  );

  return (
    <>
      <div className="mb-5.5 flex flex-wrap items-center justify-between gap-5 rounded-card bg-gradient-to-r from-navy-900 to-navy-700 px-6.5 py-5.5 text-[#f1f0fa]">
        <div>
          <h2 className="m-0 mb-1 font-serif text-[22px] font-semibold">Welcome, Meirylene 👋</h2>
          <p className="m-0 max-w-[520px] text-[13px] leading-relaxed text-[#c3c3de]">
            Here you can request authorizations, submit training jobs, track
            progress, and view the event history of your research.
          </p>
        </div>
        <div className="flex flex-none items-center gap-2.5 whitespace-nowrap rounded-[11px] border border-white/[0.14] bg-white/[0.07] px-4 py-2.5 text-xs text-[#e2e0f5]">
          <ShieldCheck size={20} className="flex-none text-gold" />
          <span>
            Responsible research. Protected data.
            <br />
            Results that make a difference.
          </span>
        </div>
      </div>

      <div className="mb-5.5 grid grid-cols-1 gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          title="Authorized jobs"
          value={counts.authorized}
          footnote="Last 30 days"
          icon={<CheckCircle2 size={15} className="text-status-green" />}
          iconBg="#e4f7ee"
          selected={filter === "authorized"}
          onClick={() => setFilter(filter === "authorized" ? "all" : "authorized")}
        />
        <StatCard
          title="Jobs in progress"
          value={counts.running}
          footnote="Currently active"
          icon={<Clock size={15} className="text-status-blue" />}
          iconBg="#e8eefb"
          selected={filter === "running"}
          onClick={() => setFilter(filter === "running" ? "all" : "running")}
        />
        <StatCard
          title="Denied jobs"
          value={counts.denied}
          footnote="Last 30 days"
          icon={<XCircle size={15} className="text-status-red" />}
          iconBg="#fbe9e8"
          selected={filter === "denied"}
          onClick={() => setFilter(filter === "denied" ? "all" : "denied")}
        />
        <StatCard
          title="Released models"
          value={counts.released}
          footnote="Ready to use"
          icon={<Boxes size={15} className="text-violet-deep" />}
          iconBg="#ece9fb"
          selected={filter === "done"}
          onClick={() => setFilter(filter === "done" ? "all" : "done")}
        />
      </div>

      <div className="grid grid-cols-1 items-start gap-4.5 xl:grid-cols-[1.65fr_1fr]">
        <div className="min-w-0">
          <Panel
            title="Your recent jobs"
            right={
              <a href="/jobs" className="text-xs font-bold text-violet-deep">
                View all →
              </a>
            }
          >
            <div className="relative min-w-0 overflow-x-auto"><JobsTable jobs={visibleJobs} /></div>
          </Panel>

          <div className="grid grid-cols-1 gap-4.5 sm:grid-cols-[1.5fr_1fr]">
            <Panel title="Resource usage (last 7 days)">
              <UsageChart data={mockResourceUsage} />
            </Panel>
            <Panel title="Most used model">
              <ModelDistributionChart data={mockModelUsage} />
            </Panel>
          </div>
        </div>

        <div className="min-w-0">
          <SandboxStatusPanel items={statusItems} />
          <AuthorizationsPanel authorizations={mockAuthorizations} />
          <Panel title="Recent ledger events" right={<Link to="/ledger" className="text-xs font-semibold text-violet-deep">View all</Link>}>
            <ul className="space-y-3 text-xs">{ledgerEvents.map(event => <li key={`${event.tx_id}-${event.event_type}`}>
              <Link className="font-semibold text-violet-deep" to={`/ledger?tx_id=${event.tx_id}`}>{event.event_type}{event.organization ? ` | ${event.organization}` : ""}</Link>
              <p className="break-all font-mono text-ink-muted">{event.tx_id}</p>
            </li>)}</ul>
          </Panel>
        </div>
      </div>
    </>
  );
}
