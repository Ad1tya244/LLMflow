"""Sign-up, sign-in, sign-out, password change and account recovery for workspace users."""

from __future__ import annotations

import hmac
import re
import time
from typing import Annotated, Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from llmflow.api.deps import (
    CSRF_HEADER,
    SESSION_COOKIE,
    Workspace,
    request_ip,
    throttle,
)
from llmflow.core.errors import GatewayError
from llmflow.core.ratelimit import SlidingWindowLimiter
from llmflow.security import passwords as pw
from llmflow.security import totp
from llmflow.security.vault import VaultError
from llmflow.storage.tenants import EmailTaken, TenantRepo

router = APIRouter(prefix="/auth", tags=["auth"])
_NAME_RE = re.compile(r"^[^\x00-\x1f\x7f<>]{1,60}$")
_GENERIC_LOGIN = "invalid email or password"


class Signup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    password: str = Field(max_length=pw.MAX_LENGTH)
    workspace_name: str = Field(min_length=1, max_length=60)
    invite_code: str = Field(default="", max_length=128)


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    password: str = Field(max_length=pw.MAX_LENGTH)


class ChangePassword(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(max_length=pw.MAX_LENGTH)
    new_password: str = Field(max_length=pw.MAX_LENGTH)


class Recover(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    recovery_code: str = Field(max_length=40)
    new_password: str = Field(max_length=pw.MAX_LENGTH)


class MfaLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mfa_token: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=40)


class MfaEnable(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=16)


class MfaDisable(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(max_length=pw.MAX_LENGTH)
    code: str = Field(min_length=1, max_length=40)


class PasswordOnly(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(max_length=pw.MAX_LENGTH)


def _repo(request: Request) -> TenantRepo:
    repo: TenantRepo | None = request.app.state.tenants
    if repo is None:
        raise GatewayError(503, "byok_not_configured", "workspaces are not enabled on this gateway")
    return repo


def _secure(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "") == "https"


def _issue(
    request: Request, payload: dict[str, Any], tenant_id: str, user_id: str, status: int = 200
) -> JSONResponse:
    """Start a cookie session; the CSRF token is returned in the body, the session id only
    as an HttpOnly cookie."""
    state = request.app.state
    settings = state.settings
    secure = _secure(request)
    if settings.session_cookie_samesite == "none" and not secure:
        raise GatewayError(500, "internal_error", "SameSite=None sessions require HTTPS")
    token, csrf = state.sessions.create("tenant", tenant_id, user_id)
    response = JSONResponse({**payload, "csrf_token": csrf}, status_code=status)
    response.set_cookie(
        SESSION_COOKIE, token, max_age=int(state.sessions.max_age_s), httponly=True,
        secure=secure, samesite=settings.session_cookie_samesite, path="/",
    )  # fmt: skip
    return response


def _profile(tenant_name: str, tenant_id: str, email: str) -> dict[str, Any]:
    return {"workspace": {"id": tenant_id, "name": tenant_name}, "user": {"email": email}}


@router.post("/signup", status_code=201)
async def signup(request: Request, body: Signup) -> JSONResponse:
    """Create a workspace and its owner. Secrets are shown once: the first API key and the
    recovery codes. Only hashes are stored."""
    repo = _repo(request)
    st = request.app.state
    if not st.settings.signup_enabled:
        raise GatewayError(403, "forbidden", "sign-up is disabled on this gateway")
    limiter: SlidingWindowLimiter = st.signup_limiter
    wait = limiter.acquire(request_ip(request))
    if wait is not None:
        raise GatewayError(429, "rate_limited", "too many sign-ups from this address",
                           {"Retry-After": str(int(wait) + 1)})  # fmt: skip
    code = st.settings.signup_code
    if code and not hmac.compare_digest(body.invite_code.encode(), code.encode()):
        raise GatewayError(403, "forbidden", "invalid invite code")
    try:
        email = pw.normalise_email(body.email)
        pw.check_policy(body.password, email)
    except (ValueError, pw.PasswordPolicyError) as exc:
        raise GatewayError(422, "invalid_request_error", str(exc)) from exc
    name = body.workspace_name.strip()
    if not _NAME_RE.match(name):
        raise GatewayError(
            422, "invalid_request_error", "workspace name contains invalid characters"
        )

    codes = pw.new_recovery_codes()
    try:
        tenant, user = await repo.create_workspace(
            name, email, pw.hash_password(body.password), [pw.hash_recovery_code(c) for c in codes]
        )
    except EmailTaken as exc:
        raise GatewayError(
            409, "conflict", "could not create an account with those details"
        ) from exc
    key, raw = await repo.create_api_key(tenant.id, "Default")
    await repo.audit(tenant.id, email, "workspace.created", ip=request_ip(request))
    await repo.audit(
        tenant.id, email, "api_key.created", f"{key.name} (…{key.last4})", request_ip(request)
    )
    payload = {**_profile(tenant.name, tenant.id, email), "api_key": raw, "recovery_codes": codes}
    return _issue(request, payload, tenant.id, user.id, 201)


@router.post("/login")
async def login(request: Request, body: Login) -> JSONResponse:
    repo = _repo(request)
    st = request.app.state
    limiter, ip = throttle(request)
    try:
        email = pw.normalise_email(body.email)
    except ValueError:
        limiter.hit(ip)
        raise GatewayError(401, "authentication_error", _GENERIC_LOGIN) from None
    auth = await repo.user_auth(email)
    now = time.time()
    locked = auth is not None and auth.locked_until > now
    # Always do the same amount of hashing work, whether or not the account exists or is locked.
    ok = pw.verify_password(body.password, None if auth is None or locked else auth.password_hash)
    if auth is None or locked or not ok:
        limiter.hit(ip)
        if auth is not None and not locked:
            await repo.record_login_failure(
                auth.user.id, st.settings.login_max_failures, st.settings.login_lock_s
            )
            await repo.audit(auth.user.tenant_id, email, "login.failed", ip=ip)
        raise GatewayError(401, "authentication_error", _GENERIC_LOGIN)
    tenant = await repo.get_tenant(auth.user.tenant_id)
    if tenant is None or tenant.disabled:
        raise GatewayError(403, "forbidden", "this workspace is disabled")
    rehash = pw.hash_password(body.password) if pw.needs_rehash(auth.password_hash) else None
    if auth.user.mfa_enabled:
        # Password is right but no session is issued yet: a second factor is required.
        if rehash:
            await repo.set_password(auth.user.id, rehash)
        token = st.mfa_challenges.create(auth.user.id)
        return JSONResponse({"mfa_required": True, "mfa_token": token})
    await repo.record_login_success(auth.user.id, rehash)
    await repo.audit(tenant.id, email, "login.succeeded", ip=ip)
    return _issue(request, _profile(tenant.name, tenant.id, email), tenant.id, auth.user.id)


@router.post("/login/mfa")
async def login_mfa(request: Request, body: MfaLogin) -> JSONResponse:
    """Second step of sign-in: a TOTP code, or a one-time recovery code as a backup factor."""
    repo = _repo(request)
    st = request.app.state
    limiter, ip = throttle(request)
    fail = GatewayError(401, "authentication_error", "invalid or expired code")
    challenge = st.mfa_challenges.peek(body.mfa_token)
    if challenge is None:
        limiter.hit(ip)
        raise fail
    auth = await repo.user_auth_by_id(challenge.user_id)
    if auth is None or not auth.user.mfa_enabled or auth.mfa_secret_ct is None or st.vault is None:
        st.mfa_challenges.consume(body.mfa_token)
        raise fail
    code = body.code.strip()
    ok, used_recovery = False, False
    if code.replace(" ", "").isdigit():
        try:
            secret = st.vault.decrypt(auth.user.id, "mfa", auth.mfa_secret_ct)
        except VaultError:
            raise fail from None
        step = totp.verify(secret, code, last_step=auth.mfa_last_step)
        if step is not None:
            await repo.set_mfa_step(auth.user.id, step)
            ok = True
    else:
        ok = used_recovery = await repo.consume_recovery_code(
            auth.user.id, pw.hash_recovery_code(code)
        )
    if not ok:
        limiter.hit(ip)
        await repo.audit(auth.user.tenant_id, auth.user.email, "mfa.failed", ip=ip)
        raise fail
    st.mfa_challenges.consume(body.mfa_token)
    tenant = await repo.get_tenant(auth.user.tenant_id)
    if tenant is None or tenant.disabled:
        raise GatewayError(403, "forbidden", "this workspace is disabled")
    await repo.record_login_success(auth.user.id)
    action = "login.recovery_code_used" if used_recovery else "login.succeeded"
    await repo.audit(tenant.id, auth.user.email, action, "mfa", ip)
    return _issue(
        request, _profile(tenant.name, tenant.id, auth.user.email), tenant.id, auth.user.id
    )


@router.post("/mfa/setup")
async def mfa_setup(request: Request, body: PasswordOnly, ws: Workspace) -> dict[str, Any]:
    """Start enrolling an authenticator app. MFA is not active until a code is confirmed."""
    repo = _repo(request)
    st = request.app.state
    auth = await repo.user_auth(ws.user.email)
    if auth is None or not pw.verify_password(body.password, auth.password_hash):
        raise GatewayError(403, "forbidden", "password is incorrect")
    if auth.user.mfa_enabled:
        raise GatewayError(409, "conflict", "two-factor authentication is already enabled")
    if st.vault is None:
        raise GatewayError(503, "byok_not_configured", "workspaces are not enabled")
    secret = totp.new_secret()
    await repo.set_mfa_pending(ws.user.id, st.vault.encrypt(ws.user.id, "mfa", secret))
    return {"secret": secret, "otpauth_uri": totp.provisioning_uri(secret, ws.user.email)}


@router.post("/mfa/enable")
async def mfa_enable(request: Request, body: MfaEnable, ws: Workspace) -> dict[str, Any]:
    repo = _repo(request)
    st = request.app.state
    auth = await repo.user_auth_by_id(ws.user.id)
    if auth is None or auth.mfa_secret_ct is None or auth.user.mfa_enabled or st.vault is None:
        raise GatewayError(409, "conflict", "start setup first")
    secret = st.vault.decrypt(ws.user.id, "mfa", auth.mfa_secret_ct)
    step = totp.verify(secret, body.code, last_step=0)
    if step is None:
        raise GatewayError(
            422, "invalid_request_error", "that code is not valid; check your device clock"
        )
    await repo.enable_mfa(ws.user.id, step)
    await repo.audit(ws.tenant.id, ws.user.email, "mfa.enabled", ip=request_ip(request))
    return {
        "status": "enabled",
        "recovery_codes_left": await repo.unused_recovery_codes(ws.user.id),
    }


@router.post("/mfa/disable")
async def mfa_disable(request: Request, body: MfaDisable, ws: Workspace) -> dict[str, str]:
    repo = _repo(request)
    st = request.app.state
    auth = await repo.user_auth_by_id(ws.user.id)
    if auth is None or not auth.user.mfa_enabled or auth.mfa_secret_ct is None or st.vault is None:
        raise GatewayError(409, "conflict", "two-factor authentication is not enabled")
    # Needs the password AND a current second factor, so a hijacked session cannot strip MFA.
    pwd = await repo.user_auth(ws.user.email)
    if pwd is None or not pw.verify_password(body.password, pwd.password_hash):
        raise GatewayError(403, "forbidden", "password is incorrect")
    secret = st.vault.decrypt(ws.user.id, "mfa", auth.mfa_secret_ct)
    if totp.verify(secret, body.code, last_step=auth.mfa_last_step) is None:
        raise GatewayError(403, "forbidden", "code is not valid")
    await repo.disable_mfa(ws.user.id)
    await repo.audit(ws.tenant.id, ws.user.email, "mfa.disabled", ip=request_ip(request))
    return {"status": "disabled"}


@router.get("/session")
async def session_probe(request: Request) -> dict[str, Any]:
    """Always 200 so a signed-out browser logs no console errors."""
    st = request.app.state
    session = st.sessions.get(request.cookies.get(SESSION_COOKIE))
    repo: TenantRepo | None = st.tenants
    if session is None or repo is None or session.tenant_id is None or session.user_id is None:
        return {"authenticated": False}
    tenant = await repo.get_tenant(session.tenant_id)
    user = await repo.get_user(session.user_id)
    if tenant is None or user is None or tenant.disabled:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "csrf_token": session.csrf,
        **_profile(tenant.name, tenant.id, user.email),
    }


@router.post("/logout")
async def logout(
    request: Request, x_llmflow_csrf: Annotated[str | None, Header()] = None
) -> JSONResponse:
    st = request.app.state
    cookie = request.cookies.get(SESSION_COOKIE)
    session = st.sessions.get(cookie)
    if session is not None and not hmac.compare_digest(
        (x_llmflow_csrf or "").encode(), session.csrf.encode()
    ):
        raise GatewayError(403, "forbidden", f"missing or invalid {CSRF_HEADER}")
    st.sessions.revoke(cookie)
    response = JSONResponse({"status": "signed_out"})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.post("/change-password")
async def change_password(request: Request, body: ChangePassword, ws: Workspace) -> JSONResponse:
    repo = _repo(request)
    auth = await repo.user_auth(ws.user.email)
    if auth is None or not pw.verify_password(body.current_password, auth.password_hash):
        raise GatewayError(403, "forbidden", "current password is incorrect")
    try:
        pw.check_policy(body.new_password, ws.user.email)
    except pw.PasswordPolicyError as exc:
        raise GatewayError(422, "invalid_request_error", str(exc)) from exc
    await repo.set_password(ws.user.id, pw.hash_password(body.new_password))
    await repo.audit(ws.tenant.id, ws.user.email, "password.changed", ip=request_ip(request))
    request.app.state.sessions.revoke_user(ws.user.id)  # signs out every device, this one included
    response = JSONResponse({"status": "password_changed"})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.post("/recover")
async def recover(request: Request, body: Recover) -> dict[str, Any]:
    """Reset a forgotten password with a one-time recovery code (no email needed)."""
    repo = _repo(request)
    limiter, ip = throttle(request)
    fail = GatewayError(401, "authentication_error", "invalid email or recovery code")
    try:
        email = pw.normalise_email(body.email)
        pw.check_policy(body.new_password, email)
    except pw.PasswordPolicyError as exc:
        raise GatewayError(422, "invalid_request_error", str(exc)) from exc
    except ValueError:
        limiter.hit(ip)
        raise fail from None
    auth = await repo.user_auth(email)
    if auth is None or not await repo.consume_recovery_code(
        auth.user.id, pw.hash_recovery_code(body.recovery_code)
    ):
        limiter.hit(ip)
        raise fail
    await repo.set_password(auth.user.id, pw.hash_password(body.new_password))
    await repo.audit(auth.user.tenant_id, email, "password.recovered", ip=ip)
    request.app.state.sessions.revoke_user(auth.user.id)
    return {
        "status": "password_reset",
        "recovery_codes_left": await repo.unused_recovery_codes(auth.user.id),
    }


@router.post("/recovery-codes")
async def regenerate_recovery_codes(
    request: Request, body: PasswordOnly, ws: Workspace
) -> dict[str, Any]:
    repo = _repo(request)
    auth = await repo.user_auth(ws.user.email)
    if auth is None or not pw.verify_password(body.password, auth.password_hash):
        raise GatewayError(403, "forbidden", "password is incorrect")
    codes = pw.new_recovery_codes()
    await repo.replace_recovery_codes(ws.user.id, [pw.hash_recovery_code(c) for c in codes])
    await repo.audit(
        ws.tenant.id, ws.user.email, "recovery_codes.regenerated", ip=request_ip(request)
    )
    return {"recovery_codes": codes}
