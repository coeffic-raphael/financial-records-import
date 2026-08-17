/** The business fields a person may correct.
 *
 * Shared so the record editor and the bulk bar cannot drift. Two lists would
 * differ silently, and the difference would only show the day a field appeared
 * on one screen and not the other.
 */
export const EDITABLE_FIELDS = [
  "reference",
  "transaction_date",
  "value_date",
  "description",
  "gross_amount",
  "fee_amount",
  "tax_amount",
  "net_amount",
  "currency",
  "counterparty_name",
  "counterparty_account",
  "country",
  "category",
  "invoice_number",
  "payment_method",
] as const;

export type EditableField = (typeof EDITABLE_FIELDS)[number];

/**
 * `reference` is missing on purpose.
 *
 * One reference across several records creates duplicates by construction --
 * uniqueness is checked within the batch. The server refuses it too: a menu
 * that merely hides it would be a suggestion, not a rule.
 */
export const BULK_EDITABLE_FIELDS = EDITABLE_FIELDS.filter(
  (field) => field !== "reference",
);

/** `counterparty_name` reads better than the column name. */
export const fieldLabel = (field: string) => field.replace(/_/g, " ");
