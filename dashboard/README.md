# LLMFlow dashboard

Static React + TypeScript single-page app (Vite). It is for **workspace users** only: sign in,
manage provider keys and API keys, see usage and routing decisions, change password, set up
two-factor authentication. There is no operator/admin UI.

Design rules: `../docs/design-system.md`.

```bash
npm install
npm run dev          # http://localhost:5173
npm run build        # static output in dist/ (deploy to Cloudflare Pages / Vercel)
npm test && npm run typecheck
```

## Configuration

| Variable (build time) | Purpose |
|---|---|
| `VITE_GATEWAY_URL` | Gateway base URL baked into the bundle (default `http://localhost:8000`). Users cannot change it at runtime. |

The gateway must list the dashboard's origin in `LLMFLOW_CORS_ORIGINS`, and use
`LLMFLOW_SESSION_COOKIE_SAMESITE=none` (HTTPS only) when the two are on different sites.

## Security notes

- Authentication is an `HttpOnly` session cookie plus a CSRF token kept in memory. Nothing secret is
  written to `localStorage`/`sessionStorage` (only the light/dark preference).
- One-time secrets (first API key, recovery codes, new API keys) are shown once and held only in
  component state until dismissed.
- `public/_headers` ships a strict CSP for static hosts (no inline scripts).
