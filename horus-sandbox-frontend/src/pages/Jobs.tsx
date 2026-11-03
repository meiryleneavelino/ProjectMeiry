import PageStub from "@/components/PageStub";
import JobsTable from "@/components/JobsTable";
import Panel from "@/components/Panel";
import { mockJobs } from "@/data/mock";

export default function Jobs() {
  return (
    <PageStub title="My jobs" description="Complete history of your training jobs.">
      <Panel title="All jobs">
        <JobsTable jobs={mockJobs} />
      </Panel>
    </PageStub>
  );
}
