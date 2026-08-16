import { useEffect, useState } from "react";

import { refreshSession } from "../lib/apiClient";
import { useAuthStore } from "../stores/authStore";

/**
 * Restores a session on boot from the refresh cookie.
 *
 * The access token lives in memory only, so a page reload loses it. Without
 * this the refresh cookie would be useless outside a mid-session expiry: every
 * reload would sign the user out and no deep link would work.
 *
 * The attempt must complete before deciding anything: redirecting to the login
 * screen while it is still in flight is exactly the bug this replaces.
 */
export function useSessionRestore(): { restoring: boolean; unreachable: boolean } {
  const hasSession = useAuthStore((state) => state.user !== null);
  const [restoring, setRestoring] = useState(!hasSession);
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    if (!restoring) return;
    let cancelled = false;

    void (async () => {
      // Goes through the SHARED refresh: StrictMode runs this effect twice, and
      // two rotations would look like a stolen token to the API.
      const outcome = await refreshSession();
      if (cancelled) return;
      // Unreachable is not "not signed in": sending someone to the login screen
      // because the API happens to be restarting loses their place for nothing.
      setUnreachable(outcome.status === "unreachable");
      setRestoring(false);
    })();

    return () => {
      cancelled = true;
    };
  }, [restoring]);

  return { restoring, unreachable };
}
