# Security review

Review date 2026-10-13, scope: `backend/` (FastAPI gateway) and `dashboard/` (static SPA), as of this commit-less working tree. Method: manual review against OWASP Top 10 (2021) and OWASP API Security Top 10 (2023), static analysis (bandit, ruff `S` rules, mypy strict), dependency audit (pip-audit, npm audit), automated security tests, and live probes against a running instance.

No system can be proven free of vulnerabilities; this document states what was checked, what was fixed, and what residual risk remains.

## Tooling results

| Check | Result |
|---|---|
| `bandit -r backend/src` | no findings |
| `ruff` with flake8-bandit (`S`) rules | clean |
| `pip-audit` (runtime + dev deps) | no known vulnerabilities |
| `npm audit` (dashboard) | 0 vulnerabilities |
| Security + session test suites (`test_security.py`, `test_session.py`, 35 tests) | pass |
| Live probes (headers, authz scopes, CORS, brute force, oversize, validation echo) | pass |

## OWASP mapping

| Risk | Controls | Status |
|---|---|---|
| A01 / API1, API5 Broken access control | Two key scopes: client keys for `/v1/*`, admin keys for `/admin/*`; scopes may not overlap (startup check). Admin API is **off** unless admin keys are configured. Cache and budgets are keyed per client key (no cross-tenant reads). | Mitigated |
| A02 Cryptographic failures | Keys compared via SHA-256 digests with `hmac.compare_digest`; raw keys are not retained. Minimum key length 16 enforced at startup. Prompts and completions are **not stored** (only metadata). HSTS emitted behind TLS. Dashboard refuses remote `http://` gateways. | Mitigated |
| A03 Injection | SQL via SQLAlchemy bound parameters only; the one DDL statement uses constant column names. Request fields forwarded upstream via an **allow-list**. Client strings logged with `%r` (no log injection). Response headers sanitised (printable ASCII). React escapes all rendered text; no `dangerouslySetInnerHTML`. | Mitigated |
| A04 Insecure design / API4 Unrestricted resource consumption | Per-key rate limit, body size cap (declared and streamed), message count, prompt size, `max_tokens` cap, `n>1` rejected, bounded attempts, upstream timeouts, bounded in-memory structures (cache LRU, limiter map), per-key daily cost and token budgets. | Mitigated |
| A05 Security misconfiguration | Secure defaults: docs/OpenAPI off, no server banner, strict CORS allow-list, CSP `default-src 'none'` on API, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Cache-Control: no-store`, `Permissions-Policy`. Dashboard ships `_headers` with a strict CSP (no inline script). Auth cannot be silently open: empty keys refuse to start. | Mitigated |
| A06 Vulnerable components | Audited clean; `backend/requirements.lock` pins runtime versions; `dashboard/package-lock.json` pins JS. | Mitigated (re-audit on each dependency change) |
| A07 / API2 Authentication failures | Failed-auth throttling per client IP (20/min default) with `Retry-After`; no distinction between "unknown key" and "wrong key"; high-entropy key requirement. | Mitigated |
| A08 Integrity failures | No dynamic code loading, no deserialisation of untrusted data beyond JSON, catalog is a trusted local file loaded with `yaml.safe_load`. | Mitigated |
| A09 Logging and monitoring | Server-generated `x-request-id` on every response; structured log of key id, IP, model; secrets never logged; unhandled errors logged server-side and returned as a generic 500. | Partial: no alerting pipeline (out of scope on free tier) |
| A10 / API7 SSRF | Provider URLs come only from the operator-controlled catalog; clients cannot influence destinations (unknown body params are dropped). | Mitigated |
| API3 Excessive data exposure | Error responses never include raw upstream text or validation input; `/admin/config` contains no secrets (tested). | Mitigated |
| API9 Improper inventory | Single versioned surface; docs endpoint disabled by default. | Mitigated |

## Fixed during this review

1. Admin endpoints were callable with any client key, so one tenant could read all tenants' logs. Now a separate admin scope, disabled by default.
2. `.env` provider keys were not read (functional bug with security impact: operators might put keys in the shell history instead). Fixed.
3. Validation errors echoed submitted values; upstream error bodies were passed to callers. Both sanitised.
4. Unknown request fields were forwarded to providers. Now allow-listed.
5. No abuse controls existed. Added rate limiting, size/shape limits, brute-force throttling, budgets.
6. Cache truthiness bug (`cache or default`) silently disabled a configured cache; fixed and tested (this is a correctness bug found while writing the cache-isolation test).
7. Log injection via the client-controlled model name; server banner disclosure.
8. Admin credential was kept in `sessionStorage`; replaced by an HttpOnly cookie session with CSRF protection and sign-out revocation. *(Superseded 2026-10-14: the admin web UI no longer exists.)* *(Superseded 2026-10-14: there is no admin web UI any more.)*
9. Dashboard Playground would have needed a client key; it now uses a session-authenticated `/account/chat` bound to the workspace's own keys.

## Residual risks and operator responsibilities

- **Dashboard session (no credential in browser storage).** The admin key is exchanged once for a random session token in an `HttpOnly`, `SameSite` (and `Secure` over HTTPS) cookie; page JavaScript cannot read it, and the key itself is discarded immediately. A per-session CSRF token lives in memory only and must be sent as `X-LLMFlow-CSRF` on every cookie-authenticated request. Sessions are server-side, hashed at rest, idle-timeout 30 min, absolute lifetime 12 h, revocable by sign-out. Residual: an XSS bug could still make authenticated requests *from the page* while it is open (it cannot exfiltrate the credential). Mitigations: strict CSP, no HTML sinks, React escaping.
- **Cross-site deployment.** If the dashboard and API are on different sites (e.g. Cloudflare Pages + Render), set `LLMFLOW_SESSION_COOKIE_SAMESITE=none` (HTTPS required; the server refuses otherwise) and keep `LLMFLOW_CORS_ORIGINS` to the exact dashboard origin. Same-site hosting can keep `lax`.
- **Dev auto-login.** `npm run dev` injects the local admin key into the Vite **dev** server so the dashboard signs in automatically. It is gated by `import.meta.env.DEV` and the variable is never set in production builds.
- **Single-instance state.** Rate limits, cooldowns, cache and budgets are process-local. Restarts reset limits (budgets are re-hydrated from the database). Do not scale horizontally without moving this state to a shared store.
- **Failed-auth throttle behind a proxy.** Without `LLMFLOW_TRUST_FORWARDED_FOR=true` all clients appear to share the proxy IP, so one attacker could throttle everyone's failed attempts. Set it when deployed behind exactly one trusted proxy (Render).
- **Free-tier providers may train on prompts** (e.g. Gemini free tier). Use `privacy: strict` for sensitive requests and keep sensitive data out of free tiers.
- **Shadow-cost budgets are estimates** at catalog list prices, not billing.
- **Denial of service.** Application-level limits exist, but volumetric DoS protection is the platform's job (Render/Cloudflare).
- **Key rotation** is by editing the environment and restarting; there is no key-management UI.
- Rotate any key that was ever pasted into chat, a screenshot, or a shell history.

## Additions after the first review

- `/admin/benchmarks` reads report files from a fixed directory; the `name` parameter is matched against files that exist and never joined into a path (tested with `../` input).
- *(Historical; superseded by the account model below.)* An `/admin/chat` playground endpoint existed briefly; it has been removed. The playground is `/account/chat`, session + CSRF protected and bound to the workspace's own keys.
- The benchmark CLI runs the gateway in-process with a throwaway random key and a separate SQLite file; it opens no network port.
- `backend/Dockerfile` is intentionally absent: the Render blueprint uses the native Python runtime with `requirements.lock`, avoiding an unaudited base image.

## Multi-tenant workspaces (bring-your-own provider keys)

Added 2026-10-14. Threat model: the gateway now stores *other people's* provider API keys.

| Control | Detail |
|---|---|
| Encryption at rest | Fernet (AES-128-CBC + HMAC-SHA256) under `LLMFLOW_MASTER_KEY`. The tenant id and provider are bound inside the plaintext and verified on decrypt, so ciphertext cannot be moved between rows or tenants (tested). |
| Key rotation | `LLMFLOW_MASTER_KEY` accepts a comma-separated list: first encrypts, all decrypt. |
| Never returned | API responses expose only the last four characters; request bodies are not logged; validation errors never echo input. |
| Verified on save | The key is checked against the provider's `/models` (URL from the operator-controlled catalog, so no SSRF) and rejected on 401/403. |
| Isolation | A workspace key routes only through that workspace's keys, with its own quota tracker, cache namespace, budget, rate limit and request log. The operator's provider keys are never used for a workspace. |
| Workspace keys | `llmf_` + 256 bits of randomness, shown once, stored as SHA-256 only, rotatable, instantly revocable; failed lookups are throttled per IP. |
| Authorization | Workspace keys cannot call `/admin/*`; operator/admin keys cannot call `/account/*`; sessions carry a role and are checked on every route (tested). |
| Sign-up abuse | Off by default; optional invite code (constant-time compare); per-IP hourly limit. |
| Decryption lifetime | Keys are decrypted lazily into provider objects held in a bounded, short-TTL cache and dropped on update/delete/rotate. |

Residual risks and operator duties:
- **The master key is a single point of failure.** Anyone with the database *and* the master key can recover tenants' provider keys. Keep it in the platform's secret store, never in git, and back it up; losing it makes stored keys unrecoverable.
- Provider keys exist in process memory while routing. A memory-disclosure bug in the host or dependencies could expose them.
- Free-tier providers with data-training terms still apply to your users' prompts; the `trains_on_data` flag is surfaced per provider.
- Account recovery: a lost workspace key cannot be recovered (only its hash exists); an operator can delete the workspace, and the user can sign up again and re-add provider keys.

## Accounts, API keys and the removal of the admin portal (2026-10-14)

Design change after review: the web UI is for **workspace users only**. Operator actions live in
`npm run ops` and `/admin/*`, which accept only a Bearer admin key (no cookies, so no CSRF surface).

| Concern | Control |
|---|---|
| People vs. apps | Separate credentials. Email + password sessions manage a workspace; API keys call `/v1/*` only. An API key sent to `/account/*` gets 403, so a leaked key cannot add provider keys, mint keys, or read the audit log (tested). |
| Passwords | argon2id (library-default parameters, re-hashed when parameters change), 12-128 characters with upper and lower case, a number and a symbol; no repeated or sequential runs (`aaaa`, `1234`, `qwer`), no common words, no email-name reuse (enforced when a password is set, not at sign-in). Wrong password and unknown email take the same hashing work and return the same message. |
| Brute force | Per-IP throttle on failures plus a per-account lockout (5 failures, 15 min) that applies even to the correct password and is not revealed to the caller. |
| Recovery | 10 one-time recovery codes (60 bits each, stored as hashes) reset the password without email; using one ends every session. Regenerating requires the password. |
| Sessions | Random token in an HttpOnly cookie, hashed server-side, idle 30 min / absolute 12 h, per-session CSRF token required on every `/account` and `/auth` call, all sessions revoked on password change/recovery. |
| API keys | `llmf_` + 256 bits, stored as SHA-256, named, individually revocable (immediate), last-used tracked, max 20 active. |
| Audit | Immutable per-workspace log: sign-ins (success and failure), password changes, recovery, key create/revoke, provider-key save/remove, with IP. Never contains secrets. |
| Dashboard | The gateway URL is fixed at build time (no user-supplied URL), nothing secret is kept in web storage, legacy storage keys are purged on load. |
| Signup | Disabled by default; optional invite code; per-IP hourly limit; duplicate emails return a generic 409. |

Known limitations (state them to users):
- **No email verification yet.** Emails are unverified identifiers; recovery uses codes. Next steps in priority order: email verification + email reset (needs an email provider), SSO (Google/GitHub), WebAuthn/passkeys.
- **No team members or roles.** One owner per workspace; the schema keeps users separate from workspaces so members can be added.
- **Account enumeration** is possible via the sign-up conflict response (a deliberate usability trade-off); login and recovery responses do not leak existence.
- **The server sees prompts and provider keys in memory.** Trust in the operator is inherent to a hosted gateway; the local-app option removes it.

## Master key rotation (2026-10-14)

`LLMFLOW_MASTER_KEY` accepts `new,old`. To rotate: prepend the new key, run
`npm run rotate-master-key -- --dry-run`, then `npm run rotate-master-key`, confirm 0 failures, and
remove the old key. Re-encryption uses Fernet's rotate, so plaintext is never written anywhere.
If a master key (or a database plus master key) may have leaked, rotation alone is not enough: the
provider keys were exposed, so users must also rotate them at their providers.

Guidance shown to users: create a **dedicated, spend-limited provider key** for LLMFlow instead of
reusing an all-powerful one, so a leak has a bounded blast radius.

## Two-factor authentication (2026-10-14)

TOTP (RFC 6238, SHA-1, 6 digits, 30 s; works with any authenticator app), optional per user.

| Control | Detail |
|---|---|
| No session before the second factor | A correct password returns only a short-lived (5 min), single-use challenge token (hashed server-side, max 5 attempts). No cookie or CSRF token is issued until the code verifies. |
| Replay protection | The last accepted time step is stored; a code (or any earlier one) is rejected on reuse. Window is +/-1 step for clock drift. |
| Secret handling | 160-bit secret, encrypted at rest with the vault (bound to the user id), shown once during enrolment. Enrolment is inactive until a code is confirmed. |
| Backup factor | The existing one-time recovery codes also complete a second-factor sign-in (consumed on use, audited as `login.recovery_code_used`). |
| Stripping MFA | Turning it off requires the password and a current code, so a hijacked session cannot remove it. |
| Audit | `mfa.enabled`, `mfa.disabled`, `mfa.failed`, `login.recovery_code_used`. |

Residual: recovery codes bypass the second factor by design (they are the lost-device path), so
they must be stored as carefully as the password. Password reset by recovery code does not disable MFA.

