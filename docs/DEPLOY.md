# Deploying on free tiers

Target: **Render** (API), **Neon** (Postgres), **Vercel** (dashboard). None require a payment method. I could not create these accounts, so this has **not** been exercised on live infrastructure; the steps follow each provider's documentation as of 2026-10-13.

## 1. Database (Neon)
1. Create a free project at neon.com. Copy the connection string (it looks like `postgresql://user:pass@ep-xxx.neon.tech/db?sslmode=require`).
2. Nothing else: the gateway creates its table on first start and normalises the URL for asyncpg.

Why not SQLite on Render: free web services have an ephemeral filesystem, so logs and budgets would reset on every restart or spin-down.

## 2. API (Render)
1. Push the repo to GitHub, then in Render choose **New → Blueprint** and select it (uses `render.yaml`).
2. When prompted, set the secrets:
   - `GROQ_API_KEY` - your Groq key (only for apps that use operator keys; workspaces bring their own)
   - `LLMFLOW_MASTER_KEY` - generate with `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. **Back it up**: without it, users' stored provider keys cannot be decrypted. Render's "generate value" is not a valid Fernet key, so do not use it here.
   - `LLMFLOW_SIGNUP_CODE` - optional invite code to keep sign-up closed
   - `LLMFLOW_DATABASE_URL` - the Neon string
   - `LLMFLOW_CORS_ORIGINS` - leave blank for now, set after step 3
3. Render generates `LLMFLOW_API_KEYS` and `LLMFLOW_ADMIN_API_KEYS`; read them from the service's Environment tab.

Free-tier behaviour to expect: the service sleeps after 15 min idle and takes about a minute to wake; 750 instance-hours/month; the dashboard shows a "may be starting up" message while it wakes. In-memory state (rate limits, cache, sessions) resets on every restart; budgets are re-hydrated from the database.

## 3. Dashboard (Vercel)
The dashboard proxies the API under `/gw` (see `dashboard/vercel.json`), so the browser sees a single
site and the session cookie stays first-party. This avoids third-party-cookie blocking (Safari,
Chrome) that would break sign-in if the dashboard called the Render domain directly.
1. In `dashboard/vercel.json`, replace `REPLACE-WITH-YOUR-RENDER-URL` with your Render service host.
2. In Vercel choose **Add New → Project**, import the repo, set **Root Directory** to `dashboard`
   (framework preset: Vite).
3. Add the environment variable `VITE_GATEWAY_URL` = `/gw`, then deploy.
4. Copy the Vercel URL into Render's `LLMFLOW_CORS_ORIGINS` (exact origin, no trailing slash) and
   redeploy the API.
5. Open the dashboard and choose **Get started** to create a workspace (set `LLMFLOW_SIGNUP_CODE`
   to require an invite code). Operator tasks use `npm run ops` with `LLMFLOW_API_URL` pointing at
   the API and `LLMFLOW_ADMIN_KEY` set to the admin key.

Applications (the OpenAI SDK) can call either the Render URL or `https://<your-app>.vercel.app/gw`.

### Search engines (SEO)
The build generates `robots.txt`, `sitemap.xml`, canonical and Open Graph URLs from one value. The
default is the current Vercel address; if you attach a custom domain, add the environment variable
`VITE_SITE_URL=https://your-domain.com` in Vercel and redeploy. Then:
1. Add the site in [Google Search Console](https://search.google.com/search-console) and
   [Bing Webmaster Tools](https://www.bing.com/webmasters).
2. Submit `https://your-domain.com/sitemap.xml`.
3. Check the social preview by pasting the URL into a chat app or a card validator.

Only the landing page is indexable: the app is behind sign-in on `#/` routes, and `/gw/` (the API
proxy) is disallowed in `robots.txt`.

## Checklist
- [ ] `LLMFLOW_API_KEYS` and `LLMFLOW_ADMIN_API_KEYS` are different, 16+ chars
- [ ] `LLMFLOW_CORS_ORIGINS` is exactly the dashboard origin
- [ ] `LLMFLOW_TRUST_FORWARDED_FOR=true` (set in the blueprint)
- [ ] `LLMFLOW_ENABLE_DOCS=false`
- [ ] run `npm run smoke -- --base-url https://<api>.onrender.com --key <client key>` equivalent: `cd backend && PYTHONPATH=src .venv/bin/python scripts/smoke_test.py --base-url ... --key ...`
