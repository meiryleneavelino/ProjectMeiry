// Types of the horus-fhir PEP API (/fhir-api). Separate ledger: Fabric fhir-channel.

export interface Persona {
  id: string;
  label: string;
  role: "admin" | "patient" | "physician" | "lab";
  msp: string;
  fhir: string | null;
}

export interface PersonaCatalog {
  notice: string;
  personas: Persona[];
  exams: Record<string, { label: string }>;
}

export interface FhirStatus {
  ledger: string;
  identity: string;
  fhir: { ok: boolean; fhirVersion?: string; error?: string };
  chain: { ok: boolean; height?: number; currentBlockHash?: string; error?: string };
}

export interface Timings {
  endorseMs?: number;
  orderMs?: number;
  commitMs?: number;
  totalMs?: number;
}

export interface Receipt {
  txId: string;
  blockNumber: number;
  timings?: Timings;
}

export interface ServiceRequestItem {
  id: string;
  exam: string;
  requester: string;
  patient?: string;
  status?: string;
}

export interface OnChainConsent {
  consentId: string;
  serviceRequestId: string;
  patientPseudo: string;
  grantee: string;
  validUntil: string;
  consentHash: string;
  status: "active" | "revoked";
  grantedAt: string;
  revokedAt?: string;
  txId: string;
}

export interface ConsentItem {
  id: string;
  fhirStatus: string;
  patient: string;
  serviceRequestId: string;
  grantee: string;
  validUntil: string;
  onChain: OnChainConsent | null;
}

export interface OnChainResource {
  reportId: string;
  serviceRequestId: string;
  patientPseudo: string;
  reportHash: string;
  securityLabel: string;
  labId: string;
  registeredAt: string;
  txId: string;
}

export interface ResultItem {
  id: string;
  serviceRequestId: string;
  exam: string;
  securityLabel: string[];
  issued: string | null;
  onChain: OnChainResource | null;
}

export interface TraceStep {
  component: "PDP" | "PAP" | "PIP" | string;
  action: string;
  result: string;
  attributes?: Record<string, string>;
}

export interface AccessOutcome {
  permitted: boolean;
  reason: string;
  httpStatus: number;
  ledger: string;
  txId: string | null;
  blockNumber: number | null;
  decisionTrace: TraceStep[];
  policy: { policyId?: string; policyVersion?: number; policyHash?: string };
  hashCheck: { onChain: string; computed: string; match: boolean } | null;
  auditEventId: string | null;
  timings: { pdpSubmitMs?: number; fhirReadMs?: number; hashMs?: number; auditMs?: number; totalMs?: number; fabric?: Timings };
  resource?: { diagnosticReport: FhirResource; observations: FhirResource[] };
}

// Minimal view of FHIR resources shown on screen.
export interface FhirResource {
  resourceType: string;
  id: string;
  status?: string;
  issued?: string;
  code?: { text?: string; coding?: { code: string; display?: string }[] };
  valueQuantity?: { value: number; unit: string };
  valueString?: string;
  meta?: { security?: { code: string; display?: string }[] };
}

export interface PolicyRule {
  type: string;
  value?: string;
  checks?: string[];
}

export interface Policy {
  policyId: string;
  version: number;
  description?: string;
  actions: string[];
  rules: PolicyRule[];
  policyHash: string;
  updatedBy: string;
  updatedAt: string;
  txId: string;
}

export interface Binding {
  target: string;
  policyId: string;
  boundBy: string;
  boundAt: string;
  txId: string;
}

export interface PolicyCatalog {
  policies: Policy[];
  bindings: Binding[];
}

export interface TimelineEntry {
  source: "on-chain" | "off-chain";
  name: string;
  component: string;
  timestamp: string;
  txId?: string | null;
  actor?: string | null;
  id?: string;
  detail: Record<string, string>;
}

export interface Verification {
  kind: "report" | "consent";
  id: string;
  onChain: string;
  computed?: string;
  computedCurrent?: string | null;
  match: boolean;
  matchesVersion?: string | null;
  currentVersion?: string | null;
  onChainStatus?: string;
  fhirStatus?: string | null;
}

export interface TransactionCheck {
  txId: string;
  validationCode: string;
  valid: boolean;
  blockNumber?: number;
}
