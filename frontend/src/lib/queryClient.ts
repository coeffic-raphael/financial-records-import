import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false, // The API client already handles the one retry that matters.
      refetchOnWindowFocus: false,
      staleTime: 5_000,
    },
  },
});

/**
 * Query keys are prefixed with the user id.
 *
 * The cache is a leak vector between two people using the same machine: it is
 * the one the server cannot close. Prefixing makes a collision between two
 * users structurally impossible, and logout clears the cache on top of that.
 */
export function scopedKey(userId: string | undefined, ...parts: unknown[]): unknown[] {
  return ["u", userId ?? "anonymous", ...parts];
}
