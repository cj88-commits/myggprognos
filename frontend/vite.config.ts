import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Relative base so the built site works whether it's served from a GitHub
// Pages project subpath (https://user.github.io/repo/) or a custom domain
// root, without needing per-repo configuration.
export default defineConfig({
  base: "./",
  plugins: [react()],
  server: {
    port: 5173,
  },
  test: {
    environment: "jsdom",
    globals: false,
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          maplibre: ["maplibre-gl"],
          recharts: ["recharts"],
        },
      },
    },
  },
});
