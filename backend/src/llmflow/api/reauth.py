"""Re-authentication before a stored secret is shown again.

Revealing a provider key or an API key needs the account password and, when two-factor is on,
a current authenticator code. Failures count toward the per-IP throttle, so a hijacked session
cannot be used to guess the password."""

from __future__ import annotations

from fastapi import Request

from llmflow.api.deps import WorkspaceSession, throttle
from llmflow.core.errors import GatewayError
from llmflow.security import passwords as pw
from llmflow.security import totp
from llmflow.storage.tenants import TenantRepo


async def confirm_identity(
    request: Request, repo: TenantRepo, ws: WorkspaceSession, password: str, code: str | None
) -> None:
    limiter, ip = throttle(request)
    auth = await repo.user_auth(ws.user.email)
    if auth is None or not pw.verify_password(password, auth.password_hash):
        limiter.hit(ip)
        raise GatewayError(403, "forbidden", "password is incorrect")
    if auth.user.mfa_enabled:
        vault = request.app.state.vault
        if not code or auth.mfa_secret_ct is None or vault is None:
            raise GatewayError(403, "forbidden", "enter the code from your authenticator app")
        secret = vault.decrypt(ws.user.id, "mfa", auth.mfa_secret_ct)
        step = totp.verify(secret, code, last_step=auth.mfa_last_step)
        if step is None:
            limiter.hit(ip)
            raise GatewayError(403, "forbidden", "code is not valid")
        await repo.set_mfa_step(ws.user.id, step)
