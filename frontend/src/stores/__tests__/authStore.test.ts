import { beforeEach, describe, expect, it } from "vitest";

import { queryClient } from "../../lib/queryClient";
import { useAuthStore } from "../authStore";

/**
 * Signing out has to clear TWO things. Emptying the store alone would leave
 * cached responses readable by whoever signs in next on the same machine --
 * the one leak vector no server-side check can close.
 */

const SESSION = {
  access_token: "token",
  token_type: "bearer",
  expires_in: 900,
  user: { id: "u1", email: "a@example.com", name: "Alice Martin", tenant_id: "t1" },
};

beforeEach(() => {
  useAuthStore.setState({ user: null, accessToken: null });
  queryClient.clear();
});

describe("sign in", () => {
  it("stores the user and the token", () => {
    useAuthStore.getState().signIn(SESSION);

    expect(useAuthStore.getState().user?.email).toBe("a@example.com");
    expect(useAuthStore.getState().accessToken).toBe("token");
  });
});

describe("sign out", () => {
  it("empties the store", () => {
    useAuthStore.getState().signIn(SESSION);
    useAuthStore.getState().signOut();

    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().accessToken).toBeNull();
  });

  it("empties the query cache as well", () => {
    queryClient.setQueryData(["u", "u1", "batches"], [{ id: "b1", name: "July" }]);
    useAuthStore.getState().signIn(SESSION);

    useAuthStore.getState().signOut();

    expect(queryClient.getQueryData(["u", "u1", "batches"])).toBeUndefined();
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
  });
});

describe("the token never reaches persistent storage", () => {
  it("writes nothing to localStorage", () => {
    useAuthStore.getState().signIn(SESSION);

    const stored = JSON.stringify(globalThis.localStorage ?? {});
    expect(stored).not.toContain("token");
  });
});
