import { inject } from "@vercel/analytics";

/** Only the page path is ever sent: no query string and no ``#`` fragment. The app's routes live in
 *  the fragment (``#/providers``) and future links could carry one-time tokens there, so neither
 *  may reach an analytics service. */
export function pageUrlForAnalytics(url: string): string {
  try {
    const u = new URL(url);
    return `${u.origin}${u.pathname}`;
  } catch {
    return url.split(/[?#]/)[0] ?? "";
  }
}

/** Vercel Web Analytics: anonymous, aggregate page views. Production builds only. */
export function initAnalytics(): void {
  if (!import.meta.env.PROD) return;
  inject({
    mode: "production",
    beforeSend: (event) => ({ ...event, url: pageUrlForAnalytics(event.url) }),
  });
}
