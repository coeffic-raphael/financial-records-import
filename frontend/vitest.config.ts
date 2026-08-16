import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    // Node by default; the files that render a hook opt into jsdom with a
    // "@vitest-environment jsdom" docblock, so only they pay for it.
    environment: "node",
  },
});
