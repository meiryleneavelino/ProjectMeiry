import type { TrainingJob, JobStatus } from "@/types";

const statusConfig: Record<JobStatus, { label: string; className: string }> = {
  running: { label: "Running", className: "text-status-blue" },
  authorized: { label: "Authorized", className: "text-violet-deep" },
  done: { label: "Completed", className: "text-status-green" },
  denied: { label: "Denied", className: "text-status-red" },
};

interface JobsTableProps {
  jobs: TrainingJob[];
}

export default function JobsTable({ jobs }: JobsTableProps) {
  return (
    <table className="w-full border-collapse text-[12.5px]">
      <thead>
        <tr>
          {["Job ID", "Model", "Dataset / organization", "Status", "Authorization", "Created at"].map(
            (h) => (
              <th
                key={h}
                className="border-b border-line px-2.5 py-2 text-left text-[11px] font-semibold text-ink-faint"
              >
                {h}
              </th>
            )
          )}
        </tr>
      </thead>
      <tbody>
        {jobs.map((job) => {
          const s = statusConfig[job.status];
          return (
            <tr key={job.id} className="hover:bg-paper">
              <td className="border-b border-line px-2.5 py-2.5 font-bold">{job.id}</td>
              <td className="border-b border-line px-2.5 py-2.5">{job.model}</td>
              <td className="border-b border-line px-2.5 py-2.5">{job.datasetOrg}</td>
              <td className="border-b border-line px-2.5 py-2.5">
                <span className={`inline-flex items-center gap-1.5 font-bold ${s.className}`}>
                  <span className="h-[7px] w-[7px] rounded-full bg-current" />
                  {s.label}
                </span>
              </td>
              <td className="border-b border-line px-2.5 py-2.5 text-ink-faint">
                {job.authorizationId ?? "—"}
              </td>
              <td className="border-b border-line px-2.5 py-2.5">
                {new Date(job.createdAt).toLocaleString("en-US")}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
