/** Shapes returned by the API. Amounts are STRINGS on purpose: a JSON number
 *  would be parsed into a float and lose precision before being displayed. */

export type RecordStatus = "NEEDS_REVIEW" | "VALID" | "VALIDATED";
export type SourceType = "CSV" | "PDF";
export type JobStatus = "PENDING" | "PROCESSING" | "SUCCEEDED" | "FAILED";

export interface ValidationError {
  field: string;
  code: string;
  message: string;
}

export interface FinancialRecord {
  id: string;
  batch_id: string;
  reference: string | null;
  transaction_date: string | null;
  value_date: string | null;
  description: string | null;
  gross_amount: string | null;
  fee_amount: string | null;
  tax_amount: string | null;
  net_amount: string | null;
  currency: string | null;
  counterparty_name: string | null;
  counterparty_account: string | null;
  country: string | null;
  category: string | null;
  invoice_number: string | null;
  payment_method: string | null;
  source_type: SourceType;
  source_document_name: string;
  extraction_confidence: string | null;
  field_confidence: Record<string, number> | null;
  status: RecordStatus;
  validation_errors: ValidationError[];
  created_at: string;
  updated_at: string;
}

export interface Batch {
  id: string;
  name: string;
  created_at: string;
}

export interface ExtractionJob {
  id: string;
  batch_id: string;
  document_name: string;
  status: JobStatus;
  provider: string | null;
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  duration_ms: number | null;
  record_count: number | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface CurrencyTotal {
  currency: string;
  net_amount: string | null;
}

export interface BatchSummary {
  batch_id: string;
  batch_name: string;
  total_records: number;
  by_status: Record<string, number>;
  by_source_type: Record<string, number>;
  documents: { source_document_name: string; count: number }[];
  extraction_jobs: Record<string, number>;
  totals_by_currency: CurrencyTotal[];
}

export interface User {
  id: string;
  email: string;
  tenant_id: string;
}

export interface Session {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface ImportResult {
  document_name: string;
  imported: number;
  by_status: Record<string, number>;
}
