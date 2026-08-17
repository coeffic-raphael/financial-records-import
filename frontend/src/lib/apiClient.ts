import { ApiError } from "./apiError";
import type { Session } from "./types";

/**
 * The single way this application talks to the API.
 *
 * No component calls fetch directly. Otherwise every view reinvents token
 * handling, and one that forgets is enough to break the session.
 */

const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "";

type TokenReader = () => string | null;
type SessionHandler = (session: Session | null) => void;

let readToken: TokenReader = () => null;
let onSessionChange: SessionHandler = () => {};

export function configureApiClient(reader: TokenReader, handler: SessionHandler): void {
  readToken = reader;
  onSessionChange = handler;
}

/**
 * A single in-flight refresh, shared by EVERY caller.
 *
 * This is not an optimisation. The API revokes a whole token family when a
 * revoked refresh token comes back, because reuse means it was copied. Two
 * rotations started at once are indistinguishable from theft, so our own
 * protection logs the user out.
 *
 * Two callers reach this, and both must share it:
 *   - the 401 retry below, when several requests fail together;
 *   - session restoration on boot, which React StrictMode invokes TWICE in
 *     development. That second call presented an already-rotated token and got
 *     the whole session revoked -- the exact failure this guards against,
 *     arriving through a path that has nothing to do with concurrency.
 */
/**
 * Three outcomes, not two.
 *
 * "The server said no" and "we could not reach the server" look the same to a
 * try/catch and are opposites in meaning. Treating both as a lost session
 * signed people out whenever the API restarted -- during a deploy, or every
 * time a dev server reloaded. A connection error says nothing about the
 * session, so it must not end one.
 */
export type RefreshOutcome =
  | { status: "renewed"; session: Session }
  | { status: "expired" }
  | { status: "unreachable" };

let refreshInFlight: Promise<RefreshOutcome> | null = null;

export async function refreshSession(): Promise<RefreshOutcome> {
  refreshInFlight ??= (async () => {
    try {
      const response = await fetch(`${BASE_URL}/api/auth/refresh`, {
        method: "POST",
        // Sends the httpOnly refresh cookie. The JavaScript never reads it.
        credentials: "include",
      });
      if (!response.ok) return { status: "expired" } as const;
      const session = (await response.json()) as Session;
      onSessionChange(session);
      return { status: "renewed", session } as const;
    } catch {
      // fetch only rejects on a network-level failure; an HTTP error is a
      // resolved response handled above.
      return { status: "unreachable" } as const;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

async function toApiError(response: Response): Promise<ApiError> {
  let code = "HTTP_ERROR";
  let message = response.statusText || "Request failed.";
  let details: Record<string, unknown> | null = null;
  try {
    const body = await response.json();
    code = body.code ?? code;
    message = body.message ?? message;
    details = body.details ?? null;
  } catch {
    // A body that is not JSON is not worth failing over.
  }
  return new ApiError(response.status, code, message, details);
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  formData?: FormData;
  expect?: "json" | "blob";
}

async function send(path: string, options: RequestOptions, token: string | null): Promise<Response> {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  return fetch(`${BASE_URL}${path}`, {
    method: options.method ?? "GET",
    headers,
    credentials: "include",
    body: options.formData ?? (options.body !== undefined ? JSON.stringify(options.body) : undefined),
  });
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const token = readToken();
  let response = await send(path, options, token);

  // A 401 is only worth refreshing when we HELD a token and the path is not an
  // authentication endpoint. Signing in with a wrong password answers 401 too,
  // and rotating a perfectly good session over it would be both wasteful and,
  // given reuse detection, a way to lose it.
  const worthRefreshing =
    response.status === 401 && token !== null && !path.startsWith("/api/auth/");

  if (worthRefreshing) {
    const outcome = await refreshSession();

    if (outcome.status === "unreachable") {
      // Keep the session: we have no evidence it ended, only that the network
      // is momentarily unavailable.
      throw new ApiError(0, "NETWORK_UNAVAILABLE", "The server is unreachable.");
    }
    if (outcome.status === "expired") {
      onSessionChange(null);
      throw await toApiError(response);
    }
    response = await send(path, options, outcome.session.access_token);

    // Still refused with a fresh token: the session is not recoverable, and
    // leaving the user apparently signed in with a token the server rejects is
    // worse than sending them back to the login screen.
    if (response.status === 401) {
      onSessionChange(null);
      throw await toApiError(response);
    }
  }

  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  if (options.expect === "blob") return (await response.blob()) as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  /** Binary responses: the document endpoint returns a file, not JSON. */
  blob: (path: string) => request<Blob>(path, { expect: "blob" }),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: "POST", body }),
  patch: <T>(path: string, body: unknown) => request<T>(path, { method: "PATCH", body }),
  upload: <T>(path: string, formData: FormData) => request<T>(path, { method: "POST", formData }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

/** Test seam: resets the shared refresh promise between cases. */
export function __resetRefreshState(): void {
  refreshInFlight = null;
}
