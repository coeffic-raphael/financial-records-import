import { api, configureApiClient } from "./apiClient";
import { useAuthStore } from "../stores/authStore";
import type { Session } from "./types";

/** Wires the API client to the store without either importing the other. */
export function installSessionBridge(): void {
  configureApiClient(
    () => useAuthStore.getState().accessToken,
    (session) => {
      if (session === null) useAuthStore.getState().signOut();
      else useAuthStore.getState().signIn(session);
    },
  );
}

export async function signIn(email: string, password: string): Promise<void> {
  const session = await api.post<Session>("/api/auth/login", { email, password });
  useAuthStore.getState().signIn(session);
}

export async function signUp(email: string, password: string): Promise<void> {
  const session = await api.post<Session>("/api/auth/register", { email, password });
  useAuthStore.getState().signIn(session);
}

export async function signOut(): Promise<void> {
  try {
    await api.post("/api/auth/logout");
  } finally {
    useAuthStore.getState().signOut();
    // A full navigation rather than a route change: it discards every piece of
    // React state still holding the previous user's data.
    window.location.replace("/login");
  }
}
