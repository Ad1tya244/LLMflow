# Deploying on free tiers

Target: **Render** (API), **Neon** (Postgres), **Vercel** (dashboard). None require a payment method. This setup was followed end to end on 2026-10-18 and is running live; the steps below follow each provider's documentation and what was learned doing it (see the notes on region, `autoDeploy` and the `/gw` proxy).

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

### Web analytics (optional)
Vercel Web Analytics counts page views anonymously. To turn it on: in Vercel open the project, go
to **Analytics**, and click **Enable**; then deploy once (enabling adds routes under
`/_vercel/insights/*` on the next deployment). The code is already in the app and only runs in
production builds. The Hobby plan includes 50,000 events a month with a one-month reporting window;
over that, collection pauses and nothing is billed. The script and its data calls are same-origin,
so the strict Content-Security-Policy in `dashboard/vercel.json` needs no change.

### Keeping the free API awake
Render's free web service sleeps after about 15 idle minutes, and waking takes 30-60 seconds (the
Vercel proxy can time out on that first call). `.github/workflows/keepalive.yml` calls `/healthz`
every 10 minutes to keep it awake.
- **Hours:** Render's free plan gives 750 instance-hours a month and one always-on service uses
  about 744, so this works only while it is the **only** free web service on the Render account.
  Redeploys add a little; watch Render's usage page, and disable the workflow if it gets close.
- **Not Neon:** `/healthz` does not touch the database on purpose. Neon's free plan has 100
  compute-hours a month, suspends after 5 idle minutes (not configurable), and resumes in a few
  hundred milliseconds, so pinging it would exhaust the quota and take the app down.
- **GitHub pauses scheduled workflows** after about 60 days without repository activity; re-enable
  it from the Actions tab. Setting a repository variable `API_URL` overrides the address.

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
