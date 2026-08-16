import type { ValidationError } from "../lib/types";

/** Presentational: the errors attached to one field. */
export function FieldErrorList({ errors }: { errors: ValidationError[] }) {
  if (errors.length === 0) return null;
  return (
    <ul className="mt-1 space-y-0.5">
      {errors.map((error) => (
        <li key={error.code} className="text-xs text-red-700">
          <span className="font-mono">{error.code}</span> — {error.message}
        </li>
      ))}
    </ul>
  );
}
