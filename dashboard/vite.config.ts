/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";
import { applySiteUrl, normaliseSiteUrl, robotsTxt, sitemapXml } from "./seo";

declare const process: { env: Record<string, string | undefined> }; // Node global; no @types/node needed

const SITE_URL = normaliseSiteUrl(process.env.VITE_SITE_URL);

/** Fills the canonical/Open Graph URLs in index.html and emits robots.txt and sitemap.xml. */
function seo(): Plugin {
  return {
    name: "llmflow-seo",
    transformIndexHtml: (html) => applySiteUrl(html, SITE_URL),
    generateBundle() {
      this.emitFile({ type: "asset", fileName: "robots.txt", source: robotsTxt(SITE_URL) });
      this.emitFile({
        type: "asset",
        fileName: "sitemap.xml",
        source: sitemapXml(SITE_URL, new Date().toISOString().slice(0, 10)),
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), seo()],
  server: { port: 5173 },
  test: { environment: "jsdom", setupFiles: ["./src/test-setup.ts"], globals: true },
});
