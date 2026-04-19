import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
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
    // Built output lives at ../src/diskdoctor/web/_static/dist so hatchling
    // picks it up via force-include.
    outDir: path.resolve(__dirname, "../src/diskdoctor/web/_static/dist"),
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});
