export type Identity = { name: string; organization: string; pseudonym: string };
export type Algorithm = {
  id: string; name: string; code_hash: string | null; score: number; executable: boolean;
  validation_source: string; report_hash: string | null; registration_tx_id: string;
};
export type SecurityReport = {
  code_hash: string; rules_hash: string; policy_hash: string; semgrep_version: string;
  score: number; counts: { high: number; medium: number; low: number };
  findings: { rule_id: string; line: number; column: number; severity: string; message: string }[];
  decision: string; reasons: string[];
};
export type Submission = {
  code_hash: string; status: string; created_at: string; reused?: boolean;
  selection: { reviewer: string; eligible: string[]; excluded: string; seed: string; selection_version: string };
  report: SecurityReport | null; report_hash: string | null; error: string | null;
  provenance: { organization: string; image: string; image_id: string; digest: string; digest_kind: string } | null;
  tx_ids: Record<string, string>;
};
export type LedgerRecord = {
  version: number; sequence: number; tx_id: string; event_type: string; recorded_at: string;
  payload: Record<string, unknown>; previous_hash: string; record_hash: string;
};
export type LedgerPage = { items: LedgerRecord[]; total: number; offset: number; limit: number };
export type GovernanceStatus = {
  ledger: { valid: boolean; sequence?: number; record_hash?: string; backend: string; error?: string };
  worker_ready: boolean; blockchain: boolean; mode: string;
};