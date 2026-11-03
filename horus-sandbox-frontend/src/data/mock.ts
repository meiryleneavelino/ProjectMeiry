import type {
  TrainingJob,
  Authorization,
  LedgerEvent,
  SandboxComponentStatus,
  ModelUsageSlice,
  ResourceUsagePoint,
} from "@/types";

// ---------------------------------------------------------------------------
// Everything in this file is mock data. In production, each export becomes an
// async function that queries the real backend, for example:
//
//   export async function fetchJobs(): Promise<TrainingJob[]> {
//     const res = await fetch("/api/jobs");
//     return res.json();
//   }
//
// and the components that currently import `mockJobs` would use React Query
// (@tanstack/react-query) to fetch and cache `fetchJobs()`.
// ---------------------------------------------------------------------------

export const mockJobs: TrainingJob[] = [
  {
    id: "JOB-2026-0147",
    model: "ResNet-50",
    datasetOrg: "Hospital A / FHIR (cardiologia)",
    status: "running",
    authorizationId: "AUTH-9821",
    createdAt: "2026-09-21T14:32:00Z",
  },
  {
    id: "JOB-2026-0146",
    model: "BERT",
    datasetOrg: "Hospital B / Clinical notes",
    status: "authorized",
    authorizationId: "AUTH-9819",
    createdAt: "2026-09-20T10:15:00Z",
  },
  {
    id: "JOB-2026-0145",
    model: "TabNet",
    datasetOrg: "Hospital C / DICOM images",
    status: "done",
    authorizationId: "AUTH-9817",
    createdAt: "2026-09-19T16:40:00Z",
  },
  {
    id: "JOB-2026-0144",
    model: "ResNet-18",
    datasetOrg: "Hospital A / FHIR (radiologia)",
    status: "denied",
    authorizationId: null,
    createdAt: "2026-09-18T09:12:00Z",
  },
  {
    id: "JOB-2026-0143",
    model: "LSTM",
    datasetOrg: "Hospital B / Vital signs",
    status: "done",
    authorizationId: "AUTH-9815",
    createdAt: "2026-09-17T11:27:00Z",
  },
];

export const mockAuthorizations: Authorization[] = [
  {
    id: "AUTH-9821",
    purpose: "FL Training",
    validFrom: "2026-09-21",
    validUntil: "2026-09-21",
    organization: "Hospital A",
    dataset: "FHIR (cardiologia)",
    state: "active",
  },
  {
    id: "AUTH-9819",
    purpose: "FL Training",
    validFrom: "2026-09-20",
    validUntil: "2026-09-20",
    organization: "Hospital B",
    dataset: "Clinical notes",
    state: "active",
  },
  {
    id: "AUTH-9817",
    purpose: "FL Training",
    validFrom: "2026-09-19",
    validUntil: "2026-09-19",
    organization: "Hospital C",
    dataset: "DICOM (image)",
    state: "active",
  },
  {
    id: "AUTH-9815",
    purpose: "FL Training",
    validFrom: "2026-09-17",
    validUntil: "2026-09-18",
    organization: "Hospital B",
    dataset: "Vital signs",
    state: "expired",
  },
];

export const mockLedgerEvents: LedgerEvent[] = [
  { id: "e1", type: "JobStarted", subject: "AUTH-9821 · JOB-2026-0147", timestamp: "2026-09-21T14:32:00Z" },
  { id: "e2", type: "AuthorizationApproved", subject: "AUTH-9821", timestamp: "2026-09-21T14:28:00Z" },
  { id: "e3", type: "PolicyCheckPassed", subject: "AUTH-9821", timestamp: "2026-09-21T14:15:00Z" },
  { id: "e4", type: "JobCreated", subject: "JOB-2026-0147", timestamp: "2026-09-21T13:50:00Z" },
  { id: "e5", type: "AuthorizationRequested", subject: "Researcher-123 · Hospital A", timestamp: "2026-09-21T13:45:00Z" },
];

export const mockSandboxStatus: SandboxComponentStatus[] = [
  { label: "Kubernetes (k3s)", value: "3/3 nodes active", healthy: true },
  { label: "Isolation (Kata / gVisor)", value: "Active", healthy: true },
  { label: "eBPF (Falco / Tetragon)", value: "Monitoring", healthy: true },
  { label: "Network (Network Policy)", value: "In effect", healthy: true },
  { label: "Ledger (Hyperledger Fabric)", value: "Connected (4 nodes)", healthy: true },
];

export const mockModelUsage: ModelUsageSlice[] = [
  { name: "ResNet", value: 37 },
  { name: "BERT", value: 25 },
  { name: "TabNet", value: 12 },
  { name: "LSTM", value: 12 },
  { name: "Others", value: 14 },
];

export const mockResourceUsage: ResourceUsagePoint[] = [
  { date: "09/15", cpu: 42, gpu: 20, memory: 35 },
  { date: "09/16", cpu: 55, gpu: 28, memory: 40 },
  { date: "09/17", cpu: 48, gpu: 30, memory: 38 },
  { date: "09/18", cpu: 60, gpu: 26, memory: 45 },
  { date: "09/19", cpu: 58, gpu: 38, memory: 50 },
  { date: "09/20", cpu: 70, gpu: 44, memory: 52 },
  { date: "09/21", cpu: 66, gpu: 40, memory: 58 },
];
