// Types that mirror what the backend (PIPSC/PDPSC/PEPSC/PAPSC + ledger)
// should return. Once the real API exists, only src/data/* needs to be
// swapped for HTTP/gRPC calls — the components should not need to change.

export type JobStatus = "running" | "authorized" | "done" | "denied";

export interface TrainingJob {
  id: string;
  model: string;
  datasetOrg: string;
  status: JobStatus;
  authorizationId: string | null;
  createdAt: string; // ISO 8601
}

export type AuthorizationState = "active" | "expired" | "revoked";

export interface Authorization {
  id: string;
  purpose: string; // e.g.: "FL Training"
  validFrom: string;
  validUntil: string;
  organization: string;
  dataset: string;
  state: AuthorizationState;
}

export type LedgerEventType =
  | "AuthorizationRequested"
  | "PolicyCheckPassed"
  | "AuthorizationApproved"
  | "AuthorizationRevoked"
  | "JobCreated"
  | "JobStarted"
  | "JobCompleted"
  | "PolicyViolation"
  | "OutputReleased";

export interface LedgerEvent {
  id: string;
  type: LedgerEventType;
  subject: string; // AUTH-xxxx or JOB-xxxx
  detail?: string;
  timestamp: string;
}

export interface SandboxComponentStatus {
  label: string;
  value: string;
  healthy: boolean;
}

export interface ModelUsageSlice {
  name: string;
  value: number;
}

export interface ResourceUsagePoint {
  date: string;
  cpu: number;
  gpu: number;
  memory: number;
}
