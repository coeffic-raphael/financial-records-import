import type { ValidationError } from "../lib/types";

/** Presentational: the errors attached to one field, shown under it. */
export function FieldErrorList({ errors }: { errors: ValidationError[] }) {
  if (errors.length === 0) return null;

  return (
    <ul className="mt-1.5 space-y-1">
      {errors.map((error) => (
        <li key={error.code} className="flex gap-1.5 text-xs text-red-700">
          <span className="mt-1.5 size-1 shrink-0 rounded-full bg-red-500" />
          <span>
            <span className="font-mono text-[11px] text-red-800">{error.code}</span>
            <br />
            {error.message}
          </span>
        </li>
      ))}
    </ul>
  );
}
