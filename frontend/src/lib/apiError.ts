/** The single error shape the API returns: {code, message, details}. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown> | null;

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** Field-level messages from a 422, keyed by field name. */
  fieldErrors(): Record<string, string> {
    const errors = this.details?.errors;
    if (!Array.isArray(errors)) return {};
    return Object.fromEntries(
      errors.flatMap((entry) => {
        const location = (entry as { loc?: unknown[] }).loc ?? [];
        const field = location[location.length - 1];
        const message = (entry as { msg?: string }).msg ?? "";
        return typeof field === "string" ? [[field, message]] : [];
      }),
    );
  }
}
