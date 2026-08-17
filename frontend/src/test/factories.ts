/** Fixtures for component tests.

A record carries twenty-odd fields; spelling them out in every test buries the
one value a test is actually about. These build a valid shape and let a test
override only what it means to exercise.
*/

import type { BatchSummary, ExtractionJob, FinancialRecord } from "../lib/types";

export function makeRecord(overrides: Partial<FinancialRecord> = {}): FinancialRecord {
  return {
    id: "rec-1",
    batch_id: "batch-1",
    reference: "TX-2026-0001",
    transaction_date: "2026-07-01",
    value_date: "2026-07-02",
    description: "Advisory fee",
    gross_amount: "1000.00",
    fee_amount: "0.00",
    tax_amount: "170.00",
    net_amount: "1170.00",
    currency: "EUR",
    counterparty_name: "ACME Advisory",
    counterparty_account: "FR7630001007941234567890185",
    country: "FR",
    category: "PROFESSIONAL_SERVICES",
    invoice_number: "INV-1",
    payment_method: "BANK_TRANSFER",
    source_type: "CSV",
    source_document_name: "transactions_import.csv",
    has_source_document: true,
    extraction_confidence: null,
    field_confidence: null,
    status: "VALID",
    validation_errors: [],
    raw_payload: {},
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

export function makeJob(overrides: Partial<ExtractionJob> = {}): ExtractionJob {
  return {
    id: "job-1",
    batch_id: "batch-1",
    document_name: "invoice.pdf",
    status: "SUCCEEDED",
    provider: "gemini",
    model: "gemini-3.5-flash",
    input_tokens: 1005,
    output_tokens: 2548,
    duration_ms: 24426,
    record_count: 1,
    error: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:24Z",
    ...overrides,
  };
}

export function makeSummary(overrides: Partial<BatchSummary> = {}): BatchSummary {
  return {
    batch_id: "batch-1",
    batch_name: "July 2026",
    total_records: 30,
    by_status: { VALID: 18, NEEDS_REVIEW: 11, VALIDATED: 1 },
    by_source_type: { CSV: 30 },
    documents: [{ source_document_name: "transactions_import.csv", count: 30 }],
    extraction_jobs: {},
    totals_by_currency: [
      { currency: "EUR", net_amount: "25449.42" },
      { currency: "CHF", net_amount: "100795.78" },
    ],
    ...overrides,
  };
}
