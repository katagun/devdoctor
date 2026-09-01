import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "src") },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8731",
        changeOrigin: false,
      },
    },
  },
  build: {
    // Built output lives at ../src/devdoctor/web/_static/dist so hatchling
    // picks it up via force-include.
    outDir: path.resolve(import.meta.dirname, "../src/devdoctor/web/_static/dist"),
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    exclude: ["node_modules", "tests/e2e/**"],
  },
});
