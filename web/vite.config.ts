import { defineConfig, type Plugin } from "vitest/config";
import react from "@vitejs/plugin-react";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const webDir = dirname(fileURLToPath(import.meta.url));
const authorityProduct = join(webDir, "dist/organicMarkdown.js");

/** Serve the sole release-layout authority product at /organicMarkdown.js in dev. */
function serveOrganicAuthority(): Plugin {
  return {
    name: "serve-organic-authority-product",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = req.url?.split("?")[0];
        if (url !== "/organicMarkdown.js") {
          next();
          return;
        }
        if (!existsSync(authorityProduct)) {
          res.statusCode = 404;
          res.end("organic markdown authority product missing — run npm run build");
          return;
        }
        res.setHeader("Content-Type", "application/javascript; charset=utf-8");
        res.end(readFileSync(authorityProduct));
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), serveOrganicAuthority()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000"
    }
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/organicAuthority.setup.ts"],
  },
});
