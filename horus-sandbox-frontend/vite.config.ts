import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    port: 5175,
    host: "127.0.0.1",
    proxy: {
      "/governance-api": {
        target: "http://127.0.0.1:8097",
        changeOrigin: true,
        rewrite: (url) => url.replace(/^\/governance-api/, ""),
        configure: (proxy) => {
          proxy.on("proxyReq", (request) => {
            try {
              const token = readFileSync(path.resolve(__dirname, "../horus-governance/.local/api-token"), "utf8").trim();
              request.setHeader("Authorization", `Bearer ${token}`);
            } catch { request.removeHeader("Authorization"); }
          });
        },
      },
      // horus-fhir PEP API (separate module/ledger); token added server-side only.
      "/fhir-api": {
        target: "http://127.0.0.1:8099",
        changeOrigin: true,
        rewrite: (url) => url.replace(/^\/fhir-api/, ""),
        configure: (proxy) => {
          proxy.on("proxyReq", (request) => {
            try {
              const token = readFileSync(path.resolve(__dirname, "../horus-fhir/.local/api-token"), "utf8").trim();
              request.setHeader("Authorization", `Bearer ${token}`);
            } catch { request.removeHeader("Authorization"); }
          });
        },
      },
      "/training-api": {
        target: "http://127.0.0.1:8096",
        changeOrigin: true,
        rewrite: (url) => url.replace(/^\/training-api/, "/api/v1/ml"),
        configure: (proxy) => {
          proxy.on("proxyReq", (request) => {
            try {
              const access = JSON.parse(readFileSync(path.resolve(__dirname,
                "../configuration/federated-training/.local/access.json"), "utf8"));
              request.setHeader("Authorization", `Bearer ${access.token}`);
            } catch {
              request.removeHeader("Authorization");
            }
          });
        },
      },
    },
  },
});
