import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/// <reference types="vitest/config" />

// Where the FastAPI backend lives when you call it directly (docs, curl, tests).
// The browser normally goes through the Vite proxy below, so same-origin applies.
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: backendUrl,
        changeOrigin: true,
      },
    },
  },
  preview: {
    proxy: {
      "/api": {
        target: backendUrl,
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["src/test/setup.ts"],
  },
});
