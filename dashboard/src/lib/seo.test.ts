import { describe, expect, it } from "vitest";
import indexHtml from "../../index.html?raw";
import { DEFAULT_SITE_URL, applySiteUrl, normaliseSiteUrl, robotsTxt, sitemapXml } from "../../seo";

describe("seo files", () => {
  it("normalises the site URL and rejects junk", () => {
    expect(normaliseSiteUrl(undefined)).toBe(DEFAULT_SITE_URL);
    expect(normaliseSiteUrl("")).toBe(DEFAULT_SITE_URL);
    expect(normaliseSiteUrl("https://example.com///")).toBe("https://example.com");
    expect(() => normaliseSiteUrl("example.com")).toThrow();
    expect(() => normaliseSiteUrl("javascript:alert(1)")).toThrow();
  });

  it("robots.txt allows crawling and points at the sitemap", () => {
    const txt = robotsTxt("https://example.com");
    expect(txt).toContain("User-agent: *");
    expect(txt).toContain("Allow: /");
    expect(txt).toContain("Disallow: /gw/");
    expect(txt).toContain("Sitemap: https://example.com/sitemap.xml");
    expect(txt).not.toMatch(/Disallow:\s*\/\s*$/m); // never blocks the whole site
  });

  it("sitemap lists the landing page with a date", () => {
    const xml = sitemapXml("https://example.com", "2026-10-18");
    expect(xml.startsWith('<?xml version="1.0" encoding="UTF-8"?>')).toBe(true);
    expect(xml).toContain("<loc>https://example.com/</loc>");
    expect(xml).toContain("<lastmod>2026-10-18</lastmod>");
  });

  it("fills every placeholder in index.html and ships the expected tags", () => {
    const html = indexHtml;
    expect(html).toContain("__SITE_URL__");
    const out = applySiteUrl(html, "https://example.com");
    expect(out).not.toContain("__SITE_URL__");
    expect(out).toContain('<link rel="canonical" href="https://example.com/" />');
    expect(out).toContain('property="og:image" content="https://example.com/og-image.png"');
    expect(out).toMatch(/<title>[^<]{20,60}<\/title>/);
    expect(out).toMatch(/name="description"\s+content="[^"]{80,160}"/);
    // structured data is valid JSON and describes the product
    const ld = /<script type="application\/ld\+json">([\s\S]*?)<\/script>/.exec(out)?.[1] ?? "";
    const graph = (JSON.parse(ld) as { "@graph": { "@type": string }[] })["@graph"];
    expect(graph.map((n) => n["@type"])).toEqual(["WebSite", "SoftwareApplication"]);
  });
});
