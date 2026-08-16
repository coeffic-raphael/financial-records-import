import { create } from "zustand";

import { queryClient } from "../lib/queryClient";
import type { Session, User } from "../lib/types";

/**
 * Session state, and nothing else.
 *
 * NO `persist` middleware. It writes to localStorage, which would undo the
 * "access token in memory only" decision in a single import and reopen the XSS
 * exposure the whole design avoids. No server data lives here either -- that
 * belongs to React Query, which already knows how to invalidate it.
 */

interface AuthState {
  user: User | null;
  accessToken: string | null;
  signIn: (session: Session) => void;
  setAccessToken: (token: string | null) => void;
  signOut: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  accessToken: null,

  signIn: (session) => set({ user: session.user, accessToken: session.access_token }),

  setAccessToken: (token) => set({ accessToken: token }),

  signOut: () => {
    set({ user: null, accessToken: null });
    // Clearing the store is not enough: cached responses would still be
    // readable by whoever signs in next on this machine.
    queryClient.clear();
  },
}));
