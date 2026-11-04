export type Identity = { name: string; organization: string; pseudonym: string };
export type Algorithm = {
  id: string; name: string; code_hash: string | null; score: number; executable: boolean;
  validation_source: string; report_hash: string | null; registration_tx_id: string | null;
};
export type SecurityReport = {
  code_hash: string; rules_hash: string; policy_hash: string; semgrep_version: string;
  score: number; counts: { high: number; medium: number; low: number };
  findings: { rule_id: string; line: number; column: number; severity: string; message: string }[];
  decision: string; reasons: string[];
};
/** drawing -> assigned -> approved | rejected | error (see docs/HORUS_GUIA_COMPLETO.md). */
export type SubmissionStatus = "drawing" | "assigned" | "approved" | "rejected" | "error";
export type Audit = {
  organization: string; report_hash: string; image_digest: string; match: boolean; tx_id: string; recorded_at: string;
};
export type Submission = {
  code_hash: string; status: SubmissionStatus; created_at: string; reused?: boolean;
  code_bytes: number; researcher_org: string; researcher_id: string;
  selection: {
    reviewer: string | null; eligible: string[]; excluded: string; seed: string | null;
    selection_version: string | null; commits: string[]; reveals: string[]; defaulted: string[];
  };
  report: SecurityReport | null; report_hash: string | null; error: string | null;
  provenance: { organization: string; msp_id: string; image_digest: string; tx_id: string; recorded_at: string } | null;
  audits: Audit[]; disputed: boolean;
  tx_ids: Record<string, string>;
  receipt?: { tx_id: string; block_number: number };
};
/** One governance event written by a chaincode transaction on the Fabric channel. */
export type LedgerEvent = {
  tx_id: string; event_type: string; recorded_at: string; msp_id: string; organization: string;
  code_hash: string; payload: Record<string, unknown>;
};
export type LedgerPage = { items: LedgerEvent[]; total: number; offset: number; limit: number };
export type LedgerTransaction = {
  tx_id: string; valid: boolean; validation_code: string; block_number?: number; block_data_hash?: string;
  events: LedgerEvent[];
};
export type LedgerHead = {
  valid: boolean; backend: string; channel?: string; height?: number; current_block_hash?: string;
  previous_block_hash?: string; peer?: string; msp_id?: string; error?: string | null;
};
export type GovernanceStatus = { ledger: LedgerHead; ledger_ready: boolean; blockchain: boolean; mode: string };
