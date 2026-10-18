/** Search-engine files generated at build time from one public site URL, so a custom domain only
 *  needs ``VITE_SITE_URL`` changed (no hand-edited sitemap or canonical tags). */

export const DEFAULT_SITE_URL = "https://llm-flow-live.vercel.app";

export function normaliseSiteUrl(raw: string | undefined): string {
  const url = (raw ?? "").trim() || DEFAULT_SITE_URL;
  if (!/^https?:\/\/[^\s/]+/.test(url)) throw new Error(`VITE_SITE_URL must be an http(s) URL, got "${url}"`);
  return url.replace(/\/+$/, "");
}

export function robotsTxt(siteUrl: string): string {
  // ``/gw/`` is the API proxy (see vercel.json): nothing there is a page worth indexing.
  return ["User-agent: *", "Allow: /", "Disallow: /gw/", "", `Sitemap: ${siteUrl}/sitemap.xml`, ""].join("\n");
}

/** Only the landing page is public: the app lives behind sign-in on hash routes, which search
 *  engines do not index as separate pages. */
export function sitemapXml(siteUrl: string, lastmod: string): string {
  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    "  <url>",
    `    <loc>${siteUrl}/</loc>`,
    `    <lastmod>${lastmod}</lastmod>`,
    "    <changefreq>monthly</changefreq>",
    "    <priority>1.0</priority>",
    "  </url>",
    "</urlset>",
    "",
  ].join("\n");
}

export function applySiteUrl(html: string, siteUrl: string): string {
  return html.replaceAll("__SITE_URL__", siteUrl);
}
