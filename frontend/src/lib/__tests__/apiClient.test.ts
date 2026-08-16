import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { __resetRefreshState, api, configureApiClient, refreshSession } from "../apiClient";
import { ApiError } from "../apiError";

/**
 * The API client is the only part of this frontend with real branching, so it
 * is the only part with tests. Everything else is covered by tsc and the build.
 */

const fetchMock = vi.fn();

/** Only the parts of Response this client reads. */
function response(status: number, body: unknown = {}): Response {
  return {
    ok: status < 400,
    status,
    statusText: "",
    json: async () => body,
  } as unknown as Response;
}

let currentToken: string | null;
let sessionChanges: unknown[];

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  __resetRefreshState();
  currentToken = "expired-token";
  sessionChanges = [];
  configureApiClient(
    () => currentToken,
    (session) => {
      currentToken = session === null ? null : (session as { access_token: string }).access_token;
      sessionChanges.push(session);
    },
  );
});

afterEach(() => vi.unstubAllGlobals());

describe("authorisation", () => {
  it("attaches the bearer token", async () => {
    fetchMock.mockResolvedValueOnce(response(200, { ok: true }));
    await api.get("/api/batches");

    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers.Authorization).toBe("Bearer expired-token");
  });

  it("always sends credentials, so the refresh cookie travels", async () => {
    fetchMock.mockResolvedValueOnce(response(200));
    await api.get("/api/batches");

    expect(fetchMock.mock.calls[0][1].credentials).toBe("include");
  });
});

describe("retry after 401", () => {
  it("refreshes once and replays the request", async () => {
    fetchMock
      .mockResolvedValueOnce(response(401))
      .mockResolvedValueOnce(response(200, { access_token: "fresh-token" }))
      .mockResolvedValueOnce(response(200, { id: "b1" }));

    const result = await api.get<{ id: string }>("/api/batches");

    expect(result.id).toBe("b1");
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[2][1].headers.Authorization).toBe("Bearer fresh-token");
  });

  it("does not loop when the refresh fails", async () => {
    fetchMock
      .mockResolvedValueOnce(response(401))
      .mockResolvedValueOnce(response(401));

    await expect(api.get("/api/batches")).rejects.toBeInstanceOf(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(sessionChanges).toContain(null);
  });

  it("never refreshes in response to a failing refresh", async () => {
    fetchMock.mockResolvedValueOnce(response(401));

    await expect(api.post("/api/auth/refresh")).rejects.toBeInstanceOf(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shares ONE refresh between concurrent failures", async () => {
    /**
     * The trap this design exists for. The API revokes a whole token family
     * when a revoked refresh token reappears, because reuse means it was
     * copied. Three parallel rotations would look exactly like theft and log
     * the user out -- by our own protection.
     */
    fetchMock.mockImplementation(async (url: string) => {
      if (url.endsWith("/api/auth/refresh")) return response(200, { access_token: "fresh" });
      const authorised = fetchMock.mock.calls.some(
        ([callUrl, init]) => !callUrl.endsWith("/refresh") && init.headers.Authorization === "Bearer fresh",
      );
      return response(authorised ? 200 : 401, {});
    });

    await Promise.all([api.get("/api/a"), api.get("/api/b"), api.get("/api/c")]);

    const refreshCalls = fetchMock.mock.calls.filter(([url]) => url.endsWith("/api/auth/refresh"));
    expect(refreshCalls).toHaveLength(1);
  });
});

describe("error mapping", () => {
  it("carries the API error shape", async () => {
    fetchMock.mockResolvedValueOnce(
      response(409, { code: "EMAIL_TAKEN", message: "Already registered.", details: null }),
    );

    await expect(api.post("/api/auth/register")).rejects.toMatchObject({
      status: 409,
      code: "EMAIL_TAKEN",
      message: "Already registered.",
    });
  });

  it("survives a body that is not JSON", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: "Server Error",
      json: async () => {
        throw new Error("not json");
      },
    } as unknown as Response);

    await expect(api.get("/api/batches")).rejects.toMatchObject({ status: 500 });
  });

  it("maps field errors from a 422", async () => {
    fetchMock.mockResolvedValueOnce(
      response(422, {
        code: "INVALID_REQUEST",
        message: "Invalid.",
        details: { errors: [{ loc: ["body", "email"], msg: "not an email" }] },
      }),
    );

    try {
      await api.post("/api/auth/register");
      expect.unreachable();
    } catch (error) {
      expect((error as ApiError).fieldErrors()).toEqual({ email: "not an email" });
    }
  });
});

describe("session restoration", () => {
  it("returns renewed with the session", async () => {
    fetchMock.mockResolvedValueOnce(
      response(200, { access_token: "t", user: { id: "u1" } }),
    );
    await expect(refreshSession()).resolves.toMatchObject({ status: "renewed" });
  });

  it("shares one rotation between simultaneous restore attempts", async () => {
    /**
     * React StrictMode invokes effects twice in development. The second call
     * presented an already-rotated token, which the API treats as theft and
     * answers by revoking the whole family -- signing the user out on every
     * page load. Nothing here is about concurrency in the usual sense.
     */
    fetchMock.mockResolvedValue(
      response(200, { access_token: "restored", user: { id: "u1" } }),
    );

    const [first, second] = await Promise.all([refreshSession(), refreshSession()]);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(first).toBe(second);
  });

  it("reports an expired session when the server refuses", async () => {
    fetchMock.mockResolvedValueOnce(response(401));
    await expect(refreshSession()).resolves.toEqual({ status: "expired" });
  });

  it("hands the full session to the store, not just the token", async () => {
    fetchMock.mockResolvedValueOnce(
      response(200, { access_token: "t", user: { id: "u1", email: "a@b.com" } }),
    );

    await refreshSession();

    expect(sessionChanges.at(-1)).toMatchObject({ user: { email: "a@b.com" } });
  });
});

describe("when a 401 is NOT worth refreshing", () => {
  it("leaves a failed sign-in alone", async () => {
    /**
     * Wrong credentials answer 401 too. Rotating a perfectly good session over
     * it would be wasteful, and with reuse detection it is a way to lose one.
     */
    currentToken = null;
    fetchMock.mockResolvedValueOnce(response(401, { code: "INVALID_CREDENTIALS" }));

    await expect(api.post("/api/auth/login")).rejects.toMatchObject({
      code: "INVALID_CREDENTIALS",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not refresh when no token was held", async () => {
    currentToken = null;
    fetchMock.mockResolvedValueOnce(response(401));

    await expect(api.get("/api/batches")).rejects.toBeInstanceOf(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("ends the session when the replay is refused too", async () => {
    /**
     * A fresh token that is still rejected means the session is gone. Leaving
     * the user apparently signed in with a token the server refuses is worse
     * than sending them back to the login screen.
     */
    fetchMock
      .mockResolvedValueOnce(response(401))
      .mockResolvedValueOnce(response(200, { access_token: "fresh", user: { id: "u1" } }))
      .mockResolvedValueOnce(response(401));

    await expect(api.get("/api/batches")).rejects.toBeInstanceOf(ApiError);
    expect(sessionChanges.at(-1)).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});


describe("an unreachable server is not an ended session", () => {
  /**
   * "The server said no" and "we could not reach the server" look identical to
   * a try/catch and mean opposite things. Treating both as a lost session
   * signed people out whenever the API restarted -- during a deploy, or every
   * time a dev server reloaded.
   */
  it("reports unreachable rather than expired", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(refreshSession()).resolves.toEqual({ status: "unreachable" });
  });

  it("keeps the session when the network fails mid-request", async () => {
    fetchMock
      .mockResolvedValueOnce(response(401))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(api.get("/api/batches")).rejects.toMatchObject({
      code: "NETWORK_UNAVAILABLE",
    });
    expect(sessionChanges).not.toContain(null);
  });

  it("still ends the session when the server actually refuses", async () => {
    fetchMock.mockResolvedValueOnce(response(401)).mockResolvedValueOnce(response(401));

    await expect(api.get("/api/batches")).rejects.toBeInstanceOf(ApiError);
    expect(sessionChanges.at(-1)).toBeNull();
  });
});
