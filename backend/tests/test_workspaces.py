"""Accounts, API keys, bring-your-own provider keys: isolation, hashing, authz boundaries."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import respx
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from llmflow.api.app import create_app
from llmflow.api.sessions import SessionStore
from llmflow.catalog import Catalog, ProviderSpec
from llmflow.core.config import Settings
from llmflow.security import passwords as pw
from llmflow.security import totp
from llmflow.security.vault import KeyVault, VaultError

from .conftest import FakeProvider

MASTER = Fernet.generate_key().decode()
ADMIN = {"Authorization": "Bearer admin-key-0123456789"}
OPERATOR = {"Authorization": "Bearer operator-key-0123456789"}
BODY = {"model": "auto", "messages": [{"role": "user", "content": "hi"}]}
PASSWORD = "Correct-Horse-Battery-7"


class Factory:
    """Records which provider key each tenant provider object was built with."""

    def __init__(self) -> None:
        self.built: list[str] = []
        self.by_key: dict[str, FakeProvider] = {}

    def __call__(self, spec: ProviderSpec, key: str) -> FakeProvider:
        self.built.append(key)
        return self.by_key.setdefault(key, FakeProvider())


class Env:
    def __init__(
        self, client: TestClient, factory: Factory, db: Path, operator: FakeProvider
    ) -> None:
        self.c, self.factory, self.db, self.operator = client, factory, db, operator


@pytest.fixture
def env(catalog: Catalog, tmp_path: Path) -> Iterator[Env]:
    factory, operator = Factory(), FakeProvider()
    db = tmp_path / "t.db"
    settings = Settings(
        _env_file=None,
        api_keys="operator-key-0123456789",
        admin_api_keys="admin-key-0123456789",
        database_url=f"sqlite+aiosqlite:///{db}",
        master_key=MASTER,
        signup_enabled=True,
        signup_limit_per_hour=1000,
    )
    app = create_app(
        settings,
        catalog=catalog,
        providers={"p1": operator, "p2": FakeProvider()},
        env={"K1": "x", "K2": "y"},
        provider_factory=factory,
    )
    with TestClient(app) as c:
        yield Env(c, factory, db, operator)


class Person:
    """A signed-in browser: its own cookie jar + CSRF header, plus the one-time API key."""

    def __init__(self, env: Env, email: str, name: str = "Acme") -> None:
        self.client = TestClient(env.c.app)
        self.client.__enter__()
        r = self.client.post(
            "/auth/signup", json={"email": email, "password": PASSWORD, "workspace_name": name}
        )
        assert r.status_code == 201, r.text
        body = r.json()
        self.api_key: str = body["api_key"]
        self.codes: list[str] = body["recovery_codes"]
        self.csrf: str = body["csrf_token"]
        self.tenant_id: str = body["workspace"]["id"]

    @property
    def h(self) -> dict[str, str]:
        return {"x-llmflow-csrf": self.csrf}

    @property
    def bearer(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def close(self) -> None:
        self.client.__exit__(None, None, None)


@pytest.fixture
def people(env: Env) -> Iterator[list[Person]]:
    made: list[Person] = []
    yield made
    for p in made:
        p.close()


def person(
    env: Env, people: list[Person], email: str = "alice@example.com", name: str = "Acme"
) -> Person:
    p = Person(env, email, name)
    people.append(p)
    return p


def save_key(p: Person, provider: str, key: str, status: int = 200) -> Any:
    with respx.mock(assert_all_called=False) as router:
        router.get("http://p1/models").respond(status, json={"data": []})
        router.get("http://p2/models").respond(status, json={"data": []})
        return p.client.put(
            f"/account/provider-keys/{provider}", headers=p.h, json={"api_key": key}
        )


# --- sign-up --------------------------------------------------------------------------------


def test_signup_issues_secrets_once_and_stores_only_hashes(env: Env, people: list[Person]) -> None:
    p = person(env, people)
    assert p.api_key.startswith("llmf_") and len(p.codes) == 10
    with sqlite3.connect(env.db) as conn:
        dump = " ".join(
            str(v)
            for table in ("tenant", "app_user", "api_key", "recovery_code")
            for row in conn.execute(f"SELECT * FROM {table}")  # noqa: S608 - fixed names
            for v in row
        )
    assert p.api_key not in dump and PASSWORD not in dump
    assert not any(c in dump for c in p.codes)
    assert "$argon2id$" in dump  # password stored as an argon2id hash


def test_signup_validation_and_duplicate_email(env: Env, people: list[Person]) -> None:
    person(env, people, "dup@example.com")
    c = env.c
    base = {"workspace_name": "X"}
    assert (
        c.post(
            "/auth/signup", json={**base, "email": "dup@example.com", "password": PASSWORD}
        ).status_code
        == 409
    )
    assert (
        c.post(
            "/auth/signup", json={**base, "email": "DUP@example.com", "password": PASSWORD}
        ).status_code
        == 409
    )
    assert (
        c.post("/auth/signup", json={**base, "email": "nope", "password": PASSWORD}).status_code
        == 422
    )
    assert (
        c.post(
            "/auth/signup", json={**base, "email": "a@example.com", "password": "short"}
        ).status_code
        == 422
    )
    assert (
        c.post(
            "/auth/signup", json={**base, "email": "bob@example.com", "password": "Bobbobbobbob-1x"}
        ).status_code
        == 422
    )
    assert (
        c.post(
            "/auth/signup", json={**base, "email": "z@example.com", "password": "a" * 20}
        ).status_code
        == 422
    )


def test_signup_gates(catalog: Catalog, tmp_path: Path) -> None:
    def build(**kw: Any) -> TestClient:
        s = Settings(_env_file=None, api_keys="operator-key-0123456789",
                     database_url=f"sqlite+aiosqlite:///{tmp_path}/{abs(hash(str(kw)))}.db",
                     master_key=MASTER, **kw)  # fmt: skip
        return TestClient(
            create_app(s, catalog=catalog, providers={"p1": FakeProvider()}, env={"K1": "x"})
        )

    body = {"email": "a@example.com", "password": PASSWORD, "workspace_name": "X"}
    with build() as c:
        assert c.post("/auth/signup", json=body).status_code == 403
        assert c.get("/public/info").json()["signup_enabled"] is False
    with build(signup_enabled=True, signup_code="s3cret-code") as c:
        assert c.post("/auth/signup", json=body).status_code == 403
        assert (
            c.post("/auth/signup", json={**body, "invite_code": "s3cret-code"}).status_code == 201
        )
    with build(signup_enabled=True, signup_limit_per_hour=2) as c:
        codes = [
            c.post("/auth/signup", json={**body, "email": f"u{i}@example.com"}).status_code
            for i in range(3)
        ]
        assert codes == [201, 201, 429]


def test_invalid_master_key_fails_fast(catalog: Catalog) -> None:
    with pytest.raises(RuntimeError, match="Fernet"):
        create_app(
            Settings(_env_file=None, api_keys="operator-key-0123456789", master_key="nope"),
            catalog=catalog,
        )


# --- login, lockout, sessions ---------------------------------------------------------------


def test_login_logout_and_session_probe(env: Env, people: list[Person]) -> None:
    person(env, people)
    c = TestClient(env.c.app)
    with c:
        assert c.get("/auth/session").json() == {"authenticated": False}
        r = c.post("/auth/login", json={"email": "ALICE@example.com", "password": PASSWORD})
        assert r.status_code == 200
        cookie = r.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie
        assert PASSWORD not in r.text and "api_key" not in r.text
        csrf = r.json()["csrf_token"]
        probe = c.get("/auth/session").json()
        assert probe["authenticated"] and probe["user"]["email"] == "alice@example.com"
        assert c.post("/auth/logout").status_code == 403  # CSRF required
        assert c.post("/auth/logout", headers={"x-llmflow-csrf": csrf}).status_code == 200
        assert c.get("/auth/session").json() == {"authenticated": False}


def test_wrong_password_and_unknown_user_are_indistinguishable(
    env: Env, people: list[Person]
) -> None:
    person(env, people)
    a = env.c.post(
        "/auth/login", json={"email": "alice@example.com", "password": "wrong password!!"}
    )
    b = env.c.post(
        "/auth/login", json={"email": "ghost@example.com", "password": "wrong password!!"}
    )
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_account_locks_after_repeated_failures_even_for_the_right_password(
    catalog: Catalog, tmp_path: Path
) -> None:
    s = Settings(_env_file=None, api_keys="operator-key-0123456789", master_key=MASTER, signup_enabled=True,
                 database_url=f"sqlite+aiosqlite:///{tmp_path}/l.db", login_max_failures=3,
                 auth_fail_limit_per_min=1000)  # fmt: skip
    with TestClient(
        create_app(s, catalog=catalog, providers={"p1": FakeProvider()}, env={"K1": "x"})
    ) as c:
        c.post(
            "/auth/signup",
            json={"email": "l@example.com", "password": PASSWORD, "workspace_name": "L"},
        )
        c.cookies.clear()
        for _ in range(3):
            assert (
                c.post(
                    "/auth/login", json={"email": "l@example.com", "password": "nope-nope-nope"}
                ).status_code
                == 401
            )
        locked = c.post("/auth/login", json={"email": "l@example.com", "password": PASSWORD})
        assert locked.status_code == 401  # generic: does not reveal that it is locked


def test_ip_throttle_on_failed_logins(catalog: Catalog, tmp_path: Path) -> None:
    s = Settings(_env_file=None, api_keys="operator-key-0123456789", master_key=MASTER,
                 database_url=f"sqlite+aiosqlite:///{tmp_path}/i.db", auth_fail_limit_per_min=3)  # fmt: skip
    with TestClient(
        create_app(s, catalog=catalog, providers={"p1": FakeProvider()}, env={"K1": "x"})
    ) as c:
        codes = [c.post("/auth/login", json={"email": f"x{i}@example.com", "password": "whatever-123456"}).status_code
                 for i in range(5)]  # fmt: skip
        assert codes[:3] == [401, 401, 401] and codes[3] == 429


def test_change_password_signs_out_everywhere(env: Env, people: list[Person]) -> None:
    p = person(env, people)
    other = TestClient(env.c.app)
    with other:
        r = other.post("/auth/login", json={"email": "alice@example.com", "password": PASSWORD})
        other_csrf = r.json()["csrf_token"]
        bad = p.client.post("/auth/change-password", headers=p.h,
                            json={"current_password": "wrong", "new_password": "Brand-New-Passphrase-4x"})  # fmt: skip
        assert bad.status_code == 403
        ok = p.client.post("/auth/change-password", headers=p.h,
                           json={"current_password": PASSWORD, "new_password": "Brand-New-Passphrase-4x"})  # fmt: skip
        assert ok.status_code == 200
        assert p.client.get("/account", headers=p.h).status_code == 401
        assert other.get("/account", headers={"x-llmflow-csrf": other_csrf}).status_code == 401
        new = TestClient(env.c.app)
        with new:
            assert (
                new.post(
                    "/auth/login", json={"email": "alice@example.com", "password": PASSWORD}
                ).status_code
                == 401
            )
            assert new.post("/auth/login", json={"email": "alice@example.com",
                                                 "password": "Brand-New-Passphrase-4x"}).status_code == 200  # fmt: skip


def test_recovery_code_resets_password_once(env: Env, people: list[Person]) -> None:
    p = person(env, people)
    body = {
        "email": "alice@example.com",
        "recovery_code": p.codes[0],
        "new_password": "Recovered-Passphrase-9k",
    }
    r = env.c.post("/auth/recover", json=body)
    assert r.status_code == 200 and r.json()["recovery_codes_left"] == 9
    assert env.c.post("/auth/recover", json=body).status_code == 401  # single use
    bad = env.c.post("/auth/recover", json={**body, "recovery_code": "AAAA-BBBB-CCCC"})
    assert bad.status_code == 401
    assert p.client.get("/account", headers=p.h).status_code == 401  # old sessions ended
    fresh = TestClient(env.c.app)
    with fresh:
        assert fresh.post("/auth/login", json={"email": "alice@example.com",
                                               "password": "Recovered-Passphrase-9k"}).status_code == 200  # fmt: skip


# --- API keys ----------------------------------------------------------------------------------


def test_api_keys_create_list_revoke_and_last_used(env: Env, people: list[Person]) -> None:
    p = person(env, people)
    save_key(p, "p1", "tenant-key-AAAAAAAA1111")
    created = p.client.post("/account/api-keys", headers=p.h, json={"name": "CI server"})
    assert created.status_code == 201
    second = created.json()
    assert second["api_key"].startswith("llmf_") and second["name"] == "CI server"
    listing = p.client.get("/account/api-keys", headers=p.h).json()["keys"]
    assert len(listing) == 2 and all("api_key" not in k for k in listing)

    h2 = {"Authorization": f"Bearer {second['api_key']}"}
    assert env.c.post("/v1/chat/completions", headers=h2, json=BODY).status_code == 200
    used = next(
        k
        for k in p.client.get("/account/api-keys", headers=p.h).json()["keys"]
        if k["id"] == second["id"]
    )
    assert used["last_used_at"] is not None

    assert p.client.delete(f"/account/api-keys/{second['id']}", headers=p.h).status_code == 200
    assert env.c.post("/v1/chat/completions", headers=h2, json=BODY).status_code == 401  # revoked
    assert (
        env.c.post("/v1/chat/completions", headers=p.bearer, json=BODY).status_code == 200
    )  # others fine
    assert p.client.delete(f"/account/api-keys/{second['id']}", headers=p.h).status_code == 404


def test_api_key_cannot_manage_the_workspace_and_session_cannot_call_v1(
    env: Env, people: list[Person]
) -> None:
    p = person(env, people)
    c = env.c
    for method, path in (
        ("get", "/account"),
        ("get", "/account/api-keys"),
        ("get", "/account/audit"),
    ):
        assert getattr(c, method)(path, headers=p.bearer).status_code == 403
    assert (
        c.put("/account/provider-keys/p1", headers=p.bearer, json={"api_key": "x" * 12}).status_code
        == 403
    )
    assert c.post("/account/api-keys", headers=p.bearer, json={"name": "evil"}).status_code == 403
    # a browser session (cookie) is not accepted as an API credential
    assert p.client.post("/v1/chat/completions", headers=p.h, json=BODY).status_code == 401


def test_management_requires_csrf(env: Env, people: list[Person]) -> None:
    p = person(env, people)
    assert p.client.get("/account").status_code == 403
    assert p.client.get("/account", headers={"x-llmflow-csrf": "wrong"}).status_code == 403
    assert p.client.get("/account", headers=p.h).status_code == 200


# --- provider keys ---------------------------------------------------------------------------


def test_new_workspace_has_no_providers_until_a_key_is_added(
    env: Env, people: list[Person]
) -> None:
    p = person(env, people)
    assert [m["id"] for m in env.c.get("/v1/models", headers=p.bearer).json()["data"]] == ["auto"]
    r = env.c.post("/v1/chat/completions", headers=p.bearer, json=BODY)
    assert r.status_code == 503 and r.json()["error"]["type"] == "no_provider_keys"


def test_provider_key_verified_encrypted_never_returned_and_routes(
    env: Env, people: list[Person]
) -> None:
    p = person(env, people)
    secret = "gsk_FAKE_canary_value_for_tests_1234"
    r = save_key(p, "p1", secret)
    assert r.status_code == 200 and r.json() == {
        "provider": "p1",
        "last4": "1234",
        "verified": True,
    }
    assert secret not in r.text
    with sqlite3.connect(env.db) as conn:
        stored = " ".join(
            str(v) for row in conn.execute("SELECT * FROM tenant_provider_key") for v in row
        )
    assert secret not in stored and "gAAAA" in stored

    acct = p.client.get("/account", headers=p.h)
    assert secret not in acct.text and env.factory.built == []  # not decrypted just to describe
    ok = env.c.post("/v1/chat/completions", headers=p.bearer, json=BODY)
    assert ok.status_code == 200
    assert (
        env.factory.built == [secret] and env.operator.calls == []
    )  # tenant's key, not the operator's


def test_two_workspaces_are_isolated(env: Env, people: list[Person]) -> None:
    a = person(env, people, "a@example.com", "A")
    b = person(env, people, "b@example.com", "B")
    save_key(a, "p1", "alice-key-AAAAAAAA1111")
    save_key(b, "p1", "bob-key-BBBBBBBB2222")
    env.c.post("/v1/chat/completions", headers=a.bearer, json=BODY)
    env.c.post("/v1/chat/completions", headers=b.bearer, json=BODY)
    env.c.post("/v1/chat/completions", headers=b.bearer, json=BODY)
    assert len(env.factory.by_key["alice-key-AAAAAAAA1111"].calls) == 1
    assert len(env.factory.by_key["bob-key-BBBBBBBB2222"].calls) == 2
    assert a.client.get("/account/requests", headers=a.h).json()["total"] == 1
    assert b.client.get("/account/requests", headers=b.h).json()["total"] == 2
    # one workspace cannot revoke another's API key by guessing its id
    a_key = a.client.get("/account/api-keys", headers=a.h).json()["keys"][0]["id"]
    assert b.client.delete(f"/account/api-keys/{a_key}", headers=b.h).status_code == 404
    assert env.c.post("/v1/chat/completions", headers=a.bearer, json=BODY).status_code == 200


def test_bad_provider_keys_are_rejected(env: Env, people: list[Person]) -> None:
    p = person(env, people)
    assert save_key(p, "p1", "definitely-bad-key-0000", status=401).status_code == 422
    assert save_key(p, "nope", "some-long-enough-key").status_code == 404
    assert save_key(p, "p1", "has spaces in it!!").status_code == 422
    stored = p.client.get("/account", headers=p.h).json()["providers"]
    assert next(x for x in stored if x["id"] == "p1")["configured"] is False


def _remove(p: Person, provider: str, password: str = PASSWORD, code: str | None = None) -> Any:
    body: dict[str, Any] = {"password": password}
    if code is not None:
        body["code"] = code
    return p.client.request("DELETE", f"/account/provider-keys/{provider}", headers=p.h, json=body)


def test_deleting_a_provider_key_stops_routing(env: Env, people: list[Person]) -> None:
    p = person(env, people)
    save_key(p, "p1", "tenant-key-AAAAAAAA1111")
    assert env.c.post("/v1/chat/completions", headers=p.bearer, json=BODY).status_code == 200
    assert _remove(p, "p1").status_code == 200
    again = env.c.post("/v1/chat/completions", headers=p.bearer, json=BODY)
    assert again.json()["error"]["type"] == "no_provider_keys"


# --- audit ---------------------------------------------------------------------------------------


def test_audit_trail_records_security_events_without_secrets(
    env: Env, people: list[Person]
) -> None:
    p = person(env, people)
    save_key(p, "p1", "tenant-key-AAAAAAAA1111")
    p.client.post("/account/api-keys", headers=p.h, json={"name": "second"})
    events = p.client.get("/account/audit", headers=p.h).json()["events"]
    actions = {e["action"] for e in events}
    assert {"workspace.created", "api_key.created", "provider_key.saved"} <= actions
    dump = str(events)
    assert "tenant-key-AAAAAAAA1111" not in dump and p.api_key not in dump


# --- operator ----------------------------------------------------------------------------------


def test_operator_can_list_disable_and_delete_without_seeing_secrets(
    env: Env, people: list[Person]
) -> None:
    p = person(env, people)
    save_key(p, "p1", "tenant-key-AAAAAAAA1111")
    listing = env.c.get("/admin/tenants", headers=ADMIN)
    row = listing.json()["tenants"][0]
    assert row["owner_email"] == "alice@example.com" and row["providers"] == ["p1"]
    assert "tenant-key-AAAAAAAA1111" not in listing.text and p.api_key not in listing.text

    assert env.c.post(f"/admin/tenants/{p.tenant_id}/disable", headers=ADMIN).status_code == 200
    assert env.c.post("/v1/chat/completions", headers=p.bearer, json=BODY).status_code == 403
    assert p.client.get("/account", headers=p.h).status_code == 401
    assert env.c.post(f"/admin/tenants/{p.tenant_id}/enable", headers=ADMIN).status_code == 200
    assert env.c.post("/v1/chat/completions", headers=p.bearer, json=BODY).status_code == 200
    assert env.c.delete(f"/admin/tenants/{p.tenant_id}", headers=ADMIN).status_code == 200
    assert env.c.post("/v1/chat/completions", headers=p.bearer, json=BODY).status_code == 401


def test_admin_surface_is_bearer_only(env: Env, people: list[Person]) -> None:
    p = person(env, people)
    assert env.c.get("/admin/overview", headers=p.bearer).status_code == 401
    assert env.c.get("/admin/overview", headers=OPERATOR).status_code == 401
    assert p.client.get("/admin/tenants", headers=p.h).status_code == 401  # session cookie: no
    assert env.c.get("/admin/overview", headers=ADMIN).status_code == 200


# --- units -----------------------------------------------------------------------------------------


def test_vault_roundtrip_binding_and_rotation() -> None:
    k1, k2 = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    v = KeyVault([k1])
    token = v.encrypt("t1", "groq", "secret-value")
    assert "secret-value" not in token and v.decrypt("t1", "groq", token) == "secret-value"
    for tenant, provider in (("t2", "groq"), ("t1", "openai")):
        with pytest.raises(VaultError):
            v.decrypt(tenant, provider, token)
    with pytest.raises(VaultError):
        v.decrypt("t1", "groq", token[:-4] + "AAAA")
    assert KeyVault([k2, k1]).decrypt("t1", "groq", token) == "secret-value"
    with pytest.raises(VaultError):
        KeyVault([k2]).decrypt("t1", "groq", token)
    with pytest.raises(VaultError):
        KeyVault([])


def test_password_policy_and_hashing() -> None:
    assert pw.verify_password("hunter2hunter2", pw.hash_password("hunter2hunter2"))
    assert not pw.verify_password("other-password!!", pw.hash_password("hunter2hunter2"))
    assert not pw.verify_password("anything", None)  # unknown user path
    weak = {
        "short": "Ab1!",
        "no uppercase": "correct-horse-battery-7",
        "no lowercase": "CORRECT-HORSE-BATTERY-7",
        "no number": "Correct-Horse-Battery",
        "no symbol": "CorrectHorseBattery7",
        "repeated run": "Correct-Horse-Bxxxx7",
        "sequence": "Correct-Horse-1234-Zq",
        "keyboard walk": "Correct-Horse-qwer-9Z",
        "common word": "Welcome-To-The-Zoo-42",
        "too long": "Aa1!" * 40,
    }
    for reason, bad in weak.items():
        with pytest.raises(pw.PasswordPolicyError):
            pw.check_policy(bad)
        assert reason  # the key documents why each case is rejected
    with pytest.raises(pw.PasswordPolicyError):
        pw.check_policy("Alicealice-1357-Zq", "alice@example.com")
    pw.check_policy("Correct-Horse-Battery-7")
    pw.check_policy("my dog Rufus eats 3 apples")  # spaces count as symbols
    assert pw.hash_recovery_code("abcd-efgh-jklm") == pw.hash_recovery_code("ABCD EFGH JKLM")
    assert len({*pw.new_recovery_codes()}) == 10


def test_session_store_expiry_bounds_and_user_revocation() -> None:
    t = [0.0]
    store = SessionStore(idle_s=10, max_age_s=100, max_sessions=3, clock=lambda: t[0])
    tok, _ = store.create("tenant", "t1", "u1")
    t[0] = 9
    assert store.get(tok) is not None
    t[0] = 25
    assert store.get(tok) is None  # idle timeout
    tokens = [store.create("tenant", "t", f"u{i}")[0] for i in range(5)]
    assert len(store) == 3 and store.get(tokens[0]) is None
    keep, _ = store.create("tenant", "t", "same")
    other, _ = store.create("tenant", "t", "same")
    assert store.revoke_user("same") == 2 and store.get(keep) is None and store.get(other) is None
    assert all(tk not in store._sessions for tk in tokens)


async def test_master_key_rotation_reencrypts_without_losing_keys(tmp_path: Path) -> None:
    from llmflow.storage.tenants import ProviderKeyRow, TenantRepo
    from llmflow.storage.usage import UsageRepo
    from llmflow.tools.rotate_master_key import rotate_all

    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    repo = UsageRepo(f"sqlite+aiosqlite:///{tmp_path}/r.db")
    await repo.init()
    tenants = TenantRepo(repo.sessions)
    t, _u = await tenants.create_workspace("R", "r@example.com", "hash", [])
    await tenants.put_provider_key(
        t.id, "groq", KeyVault([old]).encrypt(t.id, "groq", "gsk_secret_value_1"), "_1"
    )

    # key list as the operator would configure it mid-rotation: new first, old after
    dry = await rotate_all(repo, KeyVault([new, old]), dry_run=True)
    assert (dry.total, dry.rotated, dry.failed) == (1, 1, 0)
    with pytest.raises(VaultError):  # dry run changed nothing: new key alone still cannot read it
        KeyVault([new]).decrypt(t.id, "groq", (await tenants.provider_keys(t.id))["groq"][0])

    done = await rotate_all(repo, KeyVault([new, old]), dry_run=False)
    assert (done.rotated, done.failed) == (1, 0)
    token = (await tenants.provider_keys(t.id))["groq"][0]
    assert (
        KeyVault([new]).decrypt(t.id, "groq", token) == "gsk_secret_value_1"
    )  # old key no longer needed
    with pytest.raises(VaultError):
        KeyVault([old]).decrypt(t.id, "groq", token)

    # a row encrypted under a key that is not in the list is reported, not silently dropped
    stranger = Fernet.generate_key().decode()
    await tenants.put_provider_key(
        t.id, "openai", KeyVault([stranger]).encrypt(t.id, "openai", "sk-x"), "x"
    )
    bad = await rotate_all(repo, KeyVault([new, old]), dry_run=False)
    assert bad.failed == 1
    _ = ProviderKeyRow  # imported for the table registration
    await repo.close()


# --- two-factor authentication ----------------------------------------------------------------


def test_totp_matches_rfc6238_vectors_and_rejects_replay() -> None:
    secret = (
        "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # RFC 6238 SHA-1 test secret ("12345678901234567890")
    )
    assert totp.code_at(secret, 59 // 30, digits=8) == "94287082"
    assert totp.code_at(secret, 1111111109 // 30, digits=8) == "07081804"
    now = 1_700_000_000.0
    step = totp.current_step(now)
    good = totp.code_at(secret, step)
    assert totp.verify(secret, good, now=now) == step
    assert totp.verify(secret, good, now=now, last_step=step) is None  # replay
    assert totp.verify(secret, totp.code_at(secret, step + 1), now=now) == step + 1  # drift window
    assert totp.verify(secret, totp.code_at(secret, step + 5), now=now) is None
    assert (
        totp.verify(secret, "12345", now=now) is None
        and totp.verify(secret, "abcdef", now=now) is None
    )
    assert totp.provisioning_uri(secret, "a@example.com").startswith(
        "otpauth://totp/LLMFlow%3Aa%40example.com"
    )


def _enable_mfa(p: Person) -> str:
    r = p.client.post("/auth/mfa/setup", headers=p.h, json={"password": PASSWORD})
    assert r.status_code == 200, r.text
    secret: str = r.json()["secret"]
    ok = p.client.post(
        "/auth/mfa/enable", headers=p.h, json={"code": totp.code_at(secret, totp.current_step())}
    )
    assert ok.status_code == 200, ok.text
    return secret


def test_mfa_setup_requires_password_and_a_valid_code(env: Env, people: list[Person]) -> None:
    p = person(env, people)
    bad = p.client.post("/auth/mfa/setup", headers=p.h, json={"password": "not the password"})
    assert bad.status_code == 403
    secret = p.client.post("/auth/mfa/setup", headers=p.h, json={"password": PASSWORD}).json()[
        "secret"
    ]
    wrong = p.client.post("/auth/mfa/enable", headers=p.h, json={"code": "000000"})
    assert wrong.status_code in (422, 409)
    assert p.client.get("/account", headers=p.h).json()["user"]["mfa_enabled"] is False  # still off
    right = p.client.post(
        "/auth/mfa/enable", headers=p.h, json={"code": totp.code_at(secret, totp.current_step())}
    )
    assert right.status_code == 200
    assert p.client.get("/account", headers=p.h).json()["user"]["mfa_enabled"] is True
    with sqlite3.connect(env.db) as conn:
        dump = " ".join(str(v) for row in conn.execute("SELECT * FROM app_user") for v in row)
    assert secret not in dump  # the TOTP secret is encrypted at rest
    assert (
        p.client.post("/auth/mfa/setup", headers=p.h, json={"password": PASSWORD}).status_code
        == 409
    )


def test_login_with_mfa_needs_second_factor_and_blocks_replay(
    env: Env, people: list[Person]
) -> None:
    p = person(env, people)
    secret = _enable_mfa(p)
    fresh = TestClient(env.c.app)
    with fresh:
        r = fresh.post("/auth/login", json={"email": "alice@example.com", "password": PASSWORD})
        assert r.status_code == 200 and r.json()["mfa_required"] is True
        assert "set-cookie" not in r.headers and "csrf_token" not in r.json()  # no session yet
        token = r.json()["mfa_token"]
        assert fresh.get("/auth/session").json() == {"authenticated": False}

        wrong = fresh.post("/auth/login/mfa", json={"mfa_token": token, "code": "000000"})
        assert wrong.status_code == 401
        code = totp.code_at(secret, totp.current_step() + 1)  # newer than the enrolment step
        ok = fresh.post("/auth/login/mfa", json={"mfa_token": token, "code": code})
        assert ok.status_code == 200 and "httponly" in ok.headers["set-cookie"].lower()
        assert fresh.get("/auth/session").json()["authenticated"] is True
        # the challenge is single-use
        again = fresh.post("/auth/login/mfa", json={"mfa_token": token, "code": code})
        assert again.status_code == 401

    other = TestClient(env.c.app)
    with other:  # the same code cannot be replayed on a new login
        t2 = other.post(
            "/auth/login", json={"email": "alice@example.com", "password": PASSWORD}
        ).json()["mfa_token"]
        replay = other.post("/auth/login/mfa", json={"mfa_token": t2, "code": code})
        assert replay.status_code == 401


def test_mfa_challenge_allows_only_a_few_attempts(env: Env, people: list[Person]) -> None:
    p = person(env, people)
    secret = _enable_mfa(p)
    c = TestClient(env.c.app)
    with c:
        token = c.post(
            "/auth/login", json={"email": "alice@example.com", "password": PASSWORD}
        ).json()["mfa_token"]
        for _ in range(5):
            assert (
                c.post("/auth/login/mfa", json={"mfa_token": token, "code": "111111"}).status_code
                == 401
            )
        right = totp.code_at(secret, totp.current_step() + 1)
        assert (
            c.post("/auth/login/mfa", json={"mfa_token": token, "code": right}).status_code == 401
        )  # exhausted


def test_recovery_code_works_as_backup_factor_once(env: Env, people: list[Person]) -> None:
    p = person(env, people)
    _enable_mfa(p)
    for attempt, expect in ((0, 200), (1, 401)):
        c = TestClient(env.c.app)
        with c:
            tok = c.post(
                "/auth/login", json={"email": "alice@example.com", "password": PASSWORD}
            ).json()["mfa_token"]
            r = c.post("/auth/login/mfa", json={"mfa_token": tok, "code": p.codes[0]})
            assert r.status_code == expect, attempt


def test_disabling_mfa_needs_password_and_a_current_code(env: Env, people: list[Person]) -> None:
    p = person(env, people)
    secret = _enable_mfa(p)
    code = totp.code_at(secret, totp.current_step() + 1)
    assert (
        p.client.post(
            "/auth/mfa/disable", headers=p.h, json={"password": "nope", "code": code}
        ).status_code
        == 403
    )
    assert (
        p.client.post(
            "/auth/mfa/disable", headers=p.h, json={"password": PASSWORD, "code": "000000"}
        ).status_code
        == 403
    )
    assert (
        p.client.post(
            "/auth/mfa/disable", headers=p.h, json={"password": PASSWORD, "code": code}
        ).status_code
        == 200
    )
    c = TestClient(env.c.app)
    with c:  # back to password-only
        assert (
            c.post("/auth/login", json={"email": "alice@example.com", "password": PASSWORD})
            .json()
            .get("mfa_required")
            is None
        )
    actions = {e["action"] for e in p.client.get("/account/audit", headers=p.h).json()["events"]}
    assert {"mfa.enabled", "mfa.disabled"} <= actions


def test_cors_preflight_allows_every_method_the_dashboard_uses(env: Env) -> None:
    """Regression: saving a provider key is a PUT. If CORS does not allow it the browser blocks
    the request and the dashboard can only say it cannot reach the gateway."""
    for method, path in (
        ("GET", "/account"),
        ("POST", "/account/api-keys"),
        ("PUT", "/account/provider-keys/p1"),
        ("DELETE", "/account/api-keys/k_x"),
        ("POST", "/auth/login"),
    ):
        r = env.c.options(
            path,
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": "content-type,x-llmflow-csrf",
            },
        )
        assert r.status_code == 200, (method, path, r.text)
        assert method in r.headers["access-control-allow-methods"]
        assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
        assert r.headers["access-control-allow-credentials"] == "true"


def test_playground_cache_hit_on_repeat(env: Env, people: list[Person]) -> None:
    p = person(env, people)
    save_key(p, "p1", "k-" + "a" * 20)
    body = {
        "model": "auto",
        "stream": False,
        "messages": [{"role": "user", "content": "who are you?"}],
        "llmflow": {"quality": "balanced", "privacy": "standard", "cache": "on"},
    }
    first = p.client.post("/account/chat", headers=p.h, json=body)
    second = p.client.post("/account/chat", headers=p.h, json=body)
    assert first.status_code == 200 and second.status_code == 200, (first.text, second.text)
    assert first.headers["x-llmflow-cache"] == "miss"
    assert second.headers["x-llmflow-cache"] == "hit"


# --- workspace settings, sessions, deletion ---------------------------------------------------


def _with_provider(env: Env, people: list[Person]) -> Person:
    p = person(env, people)
    assert save_key(p, "p1", "k-" + "a" * 20).status_code == 200
    return p


def test_settings_default_validate_and_audit(env: Env, people: list[Person]) -> None:
    p = person(env, people)
    got = p.client.get("/account/settings", headers=p.h).json()
    assert got["cache_mode"] == "auto" and got["default_quality"] == "balanced"
    assert got["daily_budget_usd"] is None and got["daily_token_budget"] is None
    for bad in (
        {"cache_mode": "sometimes"},
        {"default_quality": "ultra"},
        {"daily_budget_usd": -1},
        {"daily_token_budget": 0},
        {"unknown": 1},
    ):
        assert p.client.put("/account/settings", headers=p.h, json=bad).status_code == 422
    ok = p.client.put(
        "/account/settings",
        headers=p.h,
        json={"cache_mode": "always", "default_quality": "high", "daily_token_budget": 5000},
    )
    assert ok.status_code == 200 and ok.json()["cache_mode"] == "always"
    assert p.client.get("/account/settings", headers=p.h).json()["daily_token_budget"] == 5000
    log = p.client.get("/account/audit", headers=p.h).json()["events"]
    assert any(e["action"] == "settings.changed" and "cache_mode" in e["detail"] for e in log)
    # an API key can never read or change workspace settings
    assert env.c.get("/account/settings", headers=p.bearer).status_code == 403


def test_workspace_cache_mode_applies_without_per_request_option(
    env: Env, people: list[Person]
) -> None:
    p = _with_provider(env, people)
    assert (
        env.c.post("/v1/chat/completions", headers=p.bearer, json=BODY).headers["x-llmflow-cache"]
        == "none"
    )  # auto: a plain request is not cached
    p.client.put("/account/settings", headers=p.h, json={"cache_mode": "always"})
    first = env.c.post("/v1/chat/completions", headers=p.bearer, json=BODY)
    second = env.c.post("/v1/chat/completions", headers=p.bearer, json=BODY)
    assert (first.headers["x-llmflow-cache"], second.headers["x-llmflow-cache"]) == ("miss", "hit")
    off = {**BODY, "llmflow": {"cache": "off"}}  # an explicit request option still wins
    assert (
        env.c.post("/v1/chat/completions", headers=p.bearer, json=off).headers["x-llmflow-cache"]
        == "none"
    )
    p.client.put("/account/settings", headers=p.h, json={"cache_mode": "off"})
    fresh = {**BODY, "messages": [{"role": "user", "content": "a different question"}]}
    on = {**fresh, "llmflow": {"cache": "on"}}  # workspace says off; the request says on
    assert (
        env.c.post("/v1/chat/completions", headers=p.bearer, json=on).headers["x-llmflow-cache"]
        == "miss"
    )


def test_workspace_default_quality_applies_unless_request_sets_it(
    env: Env, people: list[Person]
) -> None:
    p = _with_provider(env, people)

    def required(body: dict[str, Any]) -> str:
        r = env.c.post("/v1/chat/completions", headers=p.bearer, json=body)
        return str(r.headers["x-llmflow-route-reason"])

    assert "quality>=0.30" in required(BODY)  # balanced default
    p.client.put("/account/settings", headers=p.h, json={"default_quality": "high"})
    assert "quality>=0.50" in required(BODY)
    assert "quality>=0.20" in required({**BODY, "llmflow": {"quality": "low"}})


def test_workspace_budget_blocks_further_requests_and_only_tightens(
    env: Env, people: list[Person]
) -> None:
    p = _with_provider(env, people)
    p.client.put("/account/settings", headers=p.h, json={"daily_token_budget": 10})
    assert env.c.post("/v1/chat/completions", headers=p.bearer, json=BODY).status_code == 200
    blocked = env.c.post("/v1/chat/completions", headers=p.bearer, json=BODY)
    assert blocked.status_code == 429 and blocked.json()["error"]["type"] == "budget_exceeded"
    other = _with_provider_other(env, people)  # another workspace is unaffected
    assert env.c.post("/v1/chat/completions", headers=other.bearer, json=BODY).status_code == 200
    p.client.put("/account/settings", headers=p.h, json={"daily_token_budget": None})
    assert env.c.post("/v1/chat/completions", headers=p.bearer, json=BODY).status_code == 200


def _with_provider_other(env: Env, people: list[Person]) -> Person:
    p = person(env, people, "other@example.com", "Other")
    assert save_key(p, "p1", "k-" + "b" * 20).status_code == 200
    return p


def _second_login(env: Env, email: str = "alice@example.com") -> tuple[TestClient, dict[str, str]]:
    other = TestClient(env.c.app)
    other.__enter__()
    r = other.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return other, {"x-llmflow-csrf": r.json()["csrf_token"]}


def test_sessions_list_revoke_others_and_single(env: Env, people: list[Person]) -> None:
    p = person(env, people)
    other, other_h = _second_login(env)
    try:
        rows = p.client.get("/account/sessions", headers=p.h).json()["sessions"]
        assert len(rows) == 2 and sum(r["current"] for r in rows) == 1
        assert all(r["created_at"] > 0 and r["last_seen_at"] > 0 for r in rows)
        current = next(r for r in rows if r["current"])["id"]
        theirs = next(r for r in rows if not r["current"])["id"]
        assert p.client.delete(f"/account/sessions/{current}", headers=p.h).status_code == 400
        assert p.client.delete("/account/sessions/nope", headers=p.h).status_code == 404
        assert p.client.delete(f"/account/sessions/{theirs}", headers=p.h).status_code == 200
        assert other.get("/account", headers=other_h).status_code == 401  # that device is out
        again, again_h = _second_login(env)
        try:
            revoked = p.client.post("/account/sessions/revoke-others", headers=p.h).json()
            assert revoked == {"revoked": 1}
            assert again.get("/account", headers=again_h).status_code == 401
            assert p.client.get("/account", headers=p.h).status_code == 200  # this one survives
        finally:
            again.__exit__(None, None, None)
    finally:
        other.__exit__(None, None, None)
    audit = p.client.get("/account/audit", headers=p.h).json()["events"]
    assert sum(e["action"] == "session.revoked" for e in audit) == 2
    # sessions are per person: an API key cannot list them
    assert env.c.get("/account/sessions", headers=p.bearer).status_code == 403


def test_delete_workspace_needs_password_and_name_then_erases_everything(
    env: Env, people: list[Person]
) -> None:
    p = _with_provider(env, people)
    assert env.c.post("/v1/chat/completions", headers=p.bearer, json=BODY).status_code == 200
    p.client.put("/account/settings", headers=p.h, json={"cache_mode": "always"})
    url = "/auth/workspace"

    def attempt(password: str, name: str) -> Any:
        return p.client.request(
            "DELETE", url, headers=p.h, json={"password": password, "confirm_name": name}
        )

    assert attempt("wrong password", "Acme").status_code == 403
    assert attempt(PASSWORD, "acme").status_code == 422  # name must match exactly
    assert p.client.get("/account", headers=p.h).status_code == 200  # nothing deleted yet
    assert attempt(PASSWORD, "Acme").status_code == 200

    assert p.client.get("/account", headers=p.h).status_code == 401  # signed out
    assert env.c.post("/v1/chat/completions", headers=p.bearer, json=BODY).status_code == 401
    gone = env.c.post("/auth/login", json={"email": "alice@example.com", "password": PASSWORD})
    assert gone.status_code == 401
    with sqlite3.connect(env.db) as conn:
        for table, col in (
            ("tenant", "id"),
            ("app_user", "tenant_id"),
            ("api_key", "tenant_id"),
            ("tenant_provider_key", "tenant_id"),
            ("audit_event", "tenant_id"),
            ("workspace_settings", "tenant_id"),
            ("request_log", "key_id"),
        ):
            count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {col} = ?",  # noqa: S608 - fixed names
                (p.tenant_id,),
            ).fetchone()[0]
            assert count == 0, table
    # the email can be used again for a brand-new workspace
    Person(env, "alice@example.com", "Fresh").close()


# --- viewing saved keys again (re-authentication required) ------------------------------------


def _reveal(p: Person, path: str, password: str = PASSWORD, code: str | None = None) -> Any:
    body: dict[str, Any] = {"password": password}
    if code is not None:
        body["code"] = code
    return p.client.post(path, headers=p.h, json=body)


def test_reveal_provider_key_needs_password_is_audited_and_never_cached(
    env: Env, people: list[Person]
) -> None:
    p = person(env, people)
    secret = "gsk_FAKE_reveal_value_for_tests_9876"
    assert save_key(p, "p1", secret).status_code == 200
    url = "/account/provider-keys/p1/reveal"

    assert _reveal(p, url, "wrong password").status_code == 403
    assert (
        env.c.post(url, headers=p.bearer, json={"password": PASSWORD}).status_code == 403
    )  # API key
    assert _reveal(p, "/account/provider-keys/p2/reveal").status_code == 404  # nothing saved there

    ok = _reveal(p, url)
    assert ok.status_code == 200 and ok.json() == {"api_key": secret}
    assert ok.headers["cache-control"] == "no-store"
    log = p.client.get("/account/audit", headers=p.h).json()["events"]
    assert any(e["action"] == "provider_key.revealed" and e["detail"] == "p1" for e in log)
    assert secret not in str(log)  # the log records the event, never the value
    # the normal account view still never carries the key
    assert secret not in p.client.get("/account", headers=p.h).text


def test_reveal_api_key_roundtrip_stored_encrypted_and_blocked_after_revoke(
    env: Env, people: list[Person]
) -> None:
    p = person(env, people)
    keys = p.client.get("/account/api-keys", headers=p.h).json()["keys"]
    assert keys[0]["revealable"] is True  # the key created at sign-up can be shown again
    first = _reveal(p, f"/account/api-keys/{keys[0]['id']}/reveal")
    assert first.status_code == 200 and first.json()["api_key"] == p.api_key

    made = p.client.post("/account/api-keys", headers=p.h, json={"name": "second"}).json()
    assert made["revealable"] is True
    again = _reveal(p, f"/account/api-keys/{made['id']}/reveal")
    assert again.json()["api_key"] == made["api_key"]
    assert env.c.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {again.json()['api_key']}"},
        json=BODY,
    ).status_code in (200, 503)  # the revealed key is a working credential

    assert _reveal(p, f"/account/api-keys/{made['id']}/reveal", "nope").status_code == 403
    with sqlite3.connect(env.db) as conn:
        stored = " ".join(
            str(v) for row in conn.execute("SELECT * FROM api_key_secret") for v in row
        )
    assert made["api_key"] not in stored and p.api_key not in stored and "gAAAA" in stored

    assert p.client.delete(f"/account/api-keys/{made['id']}", headers=p.h).status_code == 200
    assert _reveal(p, f"/account/api-keys/{made['id']}/reveal").status_code == 404  # revoked
    rows = p.client.get("/account/api-keys", headers=p.h).json()["keys"]
    assert next(k for k in rows if k["id"] == made["id"])["revealable"] is False
    assert _reveal(p, "/account/api-keys/k_unknown/reveal").status_code == 404
    audit = p.client.get("/account/audit", headers=p.h).json()["events"]
    assert sum(e["action"] == "api_key.revealed" for e in audit) == 2


def test_reveal_requires_the_second_factor_when_enabled(env: Env, people: list[Person]) -> None:
    p = person(env, people)
    assert save_key(p, "p1", "gsk_FAKE_mfa_reveal_value_0001").status_code == 200
    secret = _enable_mfa(p)
    url = "/account/provider-keys/p1/reveal"
    assert _reveal(p, url).status_code == 403  # password alone is not enough now
    assert _reveal(p, url, code="000000").status_code == 403
    step = totp.current_step() + 1  # the enabling step cannot be replayed
    ok = _reveal(p, url, code=totp.code_at(secret, step))
    assert ok.status_code == 200 and ok.json()["api_key"] == "gsk_FAKE_mfa_reveal_value_0001"
    assert _reveal(p, url, code=totp.code_at(secret, step)).status_code == 403  # no replay


def test_deleting_a_workspace_erases_stored_api_key_secrets(env: Env, people: list[Person]) -> None:
    p = person(env, people)
    with sqlite3.connect(env.db) as conn:
        before = conn.execute(
            "SELECT COUNT(*) FROM api_key_secret WHERE tenant_id = ?", (p.tenant_id,)
        ).fetchone()[0]
    assert before == 1
    gone = p.client.request(
        "DELETE",
        "/auth/workspace",
        headers=p.h,
        json={"password": PASSWORD, "confirm_name": "Acme"},
    )
    assert gone.status_code == 200
    with sqlite3.connect(env.db) as conn:
        after = conn.execute(
            "SELECT COUNT(*) FROM api_key_secret WHERE tenant_id = ?", (p.tenant_id,)
        ).fetchone()[0]
    assert after == 0


# --- removing a provider key needs the password; pausing is reversible and does not -----------


def test_removing_a_provider_key_requires_password_and_second_factor(
    env: Env, people: list[Person]
) -> None:
    p = person(env, people)
    assert save_key(p, "p1", "tenant-key-AAAAAAAA1111").status_code == 200
    no_body = p.client.delete("/account/provider-keys/p1", headers=p.h)
    assert no_body.status_code == 422  # a bare click can never remove it
    assert _remove(p, "p1", "wrong password").status_code == 403
    still = next(
        x for x in p.client.get("/account", headers=p.h).json()["providers"] if x["id"] == "p1"
    )
    assert still["configured"] is True  # nothing was removed
    assert (
        env.c.request(
            "DELETE", "/account/provider-keys/p1", headers=p.bearer, json={"password": PASSWORD}
        ).status_code
        == 403
    )  # API keys cannot either

    secret = _enable_mfa(p)
    assert _remove(p, "p1").status_code == 403  # password alone is not enough with 2FA on
    code = totp.code_at(secret, totp.current_step() + 1)
    assert _remove(p, "p1", code=code).status_code == 200
    audit = p.client.get("/account/audit", headers=p.h).json()["events"]
    assert any(e["action"] == "provider_key.removed" for e in audit)


def test_pausing_a_provider_stops_routing_without_removing_the_key(
    env: Env, people: list[Person]
) -> None:
    p = person(env, people)
    assert save_key(p, "p1", "tenant-key-AAAAAAAA1111").status_code == 200
    url = "/account/provider-keys/p1/pause"
    ok = env.c.post("/v1/chat/completions", headers=p.bearer, json=BODY)
    assert ok.status_code == 200

    paused = p.client.put(url, headers=p.h, json={"paused": True})  # no password needed
    assert paused.status_code == 200 and paused.json() == {"provider": "p1", "paused": True}
    info = p.client.get("/account", headers=p.h).json()
    row = next(x for x in info["providers"] if x["id"] == "p1")
    assert row["configured"] is True and row["last4"] == "1111" and row["paused"] is True
    assert not any(m["enabled"] for m in info["models"] if m["provider"] == "p1")
    blocked = env.c.post("/v1/chat/completions", headers=p.bearer, json=BODY)
    assert blocked.json()["error"]["type"] == "no_provider_keys"
    assert [m["id"] for m in env.c.get("/v1/models", headers=p.bearer).json()["data"]] == ["auto"]
    named = env.c.post("/v1/chat/completions", headers=p.bearer, json={**BODY, "model": "small"})
    assert named.status_code in (404, 503)  # a paused provider cannot be reached by name either

    resumed = p.client.put(url, headers=p.h, json={"paused": False})
    assert resumed.status_code == 200
    assert (
        next(
            x for x in p.client.get("/account", headers=p.h).json()["providers"] if x["id"] == "p1"
        )["paused"]
        is False
    )
    assert env.c.post("/v1/chat/completions", headers=p.bearer, json=BODY).status_code == 200

    audit = p.client.get("/account/audit", headers=p.h).json()["events"]
    actions = [e["action"] for e in audit]
    assert "provider_key.paused" in actions and "provider_key.resumed" in actions


def test_pause_is_per_workspace_and_needs_a_saved_key_and_a_session(
    env: Env, people: list[Person]
) -> None:
    a = person(env, people, "a@example.com", "A")
    b = person(env, people, "b@example.com", "B")
    assert save_key(a, "p1", "tenant-key-AAAAAAAA1111").status_code == 200
    assert save_key(b, "p1", "tenant-key-BBBBBBBB2222").status_code == 200
    assert (
        a.client.put(
            "/account/provider-keys/p2/pause", headers=a.h, json={"paused": True}
        ).status_code
        == 404
    )
    assert (
        env.c.put(
            "/account/provider-keys/p1/pause", headers=a.bearer, json={"paused": True}
        ).status_code
        == 403
    )
    assert (
        a.client.put(
            "/account/provider-keys/p1/pause", headers=a.h, json={"paused": True}
        ).status_code
        == 200
    )
    assert env.c.post("/v1/chat/completions", headers=a.bearer, json=BODY).status_code == 503
    assert (
        env.c.post("/v1/chat/completions", headers=b.bearer, json=BODY).status_code == 200
    )  # unaffected


def test_removing_a_key_clears_its_pause_and_deleting_the_workspace_erases_it(
    env: Env, people: list[Person]
) -> None:
    p = person(env, people)
    assert save_key(p, "p1", "tenant-key-AAAAAAAA1111").status_code == 200
    p.client.put("/account/provider-keys/p1/pause", headers=p.h, json={"paused": True})
    assert _remove(p, "p1").status_code == 200
    assert save_key(p, "p1", "tenant-key-CCCCCCCC3333").status_code == 200  # a fresh key is active
    row = next(
        x for x in p.client.get("/account", headers=p.h).json()["providers"] if x["id"] == "p1"
    )
    assert row["paused"] is False
    p.client.put("/account/provider-keys/p1/pause", headers=p.h, json={"paused": True})
    gone = p.client.request(
        "DELETE",
        "/auth/workspace",
        headers=p.h,
        json={"password": PASSWORD, "confirm_name": "Acme"},
    )
    assert gone.status_code == 200
    with sqlite3.connect(env.db) as conn:
        left = conn.execute(
            "SELECT COUNT(*) FROM provider_pause WHERE tenant_id = ?", (p.tenant_id,)
        ).fetchone()[0]
    assert left == 0


def _app(catalog: Catalog, tmp_path: Path) -> Any:
    s = Settings(_env_file=None, api_keys="operator-key-0123456789",
                 database_url=f"sqlite+aiosqlite:///{tmp_path}/wake.db",
                 master_key=MASTER, signup_enabled=True)  # fmt: skip
    return create_app(s, catalog=catalog, providers={"p1": FakeProvider()}, env={"K1": "x"})


def test_sign_in_waits_for_a_resuming_database_and_checks_only_when_cold(
    catalog: Catalog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from llmflow.storage.usage import UsageRepo

    pings = 0
    real_ping = UsageRepo.ping

    async def counting_ping(self: UsageRepo, attempts: int = 4, delay_s: float = 1.5) -> bool:
        nonlocal pings
        pings += 1
        return await real_ping(self, attempts, 0.0)

    monkeypatch.setattr(UsageRepo, "ping", counting_ping)
    body = {"email": "a@example.com", "password": PASSWORD, "workspace_name": "X"}
    with TestClient(_app(catalog, tmp_path)) as c:
        assert c.post("/auth/signup", json=body).status_code == 201
        login = {"email": body["email"], "password": PASSWORD}
        for _ in range(3):
            assert c.post("/auth/login", json=login).status_code == 200
    assert pings == 1  # the first call woke it; the rest rode on the recent success


def test_sign_in_reports_503_when_the_database_does_not_come_up(
    catalog: Catalog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from llmflow.storage.usage import UsageRepo

    async def never(self: UsageRepo, attempts: int = 4, delay_s: float = 1.5) -> bool:
        return False

    monkeypatch.setattr(UsageRepo, "ping", never)
    body = {"email": "a@example.com", "password": PASSWORD}
    with TestClient(_app(catalog, tmp_path)) as c:
        r = c.post("/auth/login", json=body)
        assert r.status_code == 503
        assert r.json()["error"]["type"] == "service_unavailable"
        assert r.headers["retry-after"] == "5"
        assert c.get("/public/info").status_code == 200  # public pages never need the database
        assert c.get("/public/warm").status_code == 404  # no public wake-up endpoint exists


async def test_ensure_awake_retries_a_refused_first_connection(tmp_path: Path) -> None:
    from llmflow.storage.usage import UsageRepo

    repo = UsageRepo(f"sqlite+aiosqlite:///{tmp_path}/retry.db")
    real = repo._engine
    attempts = 0

    class Flaky:
        """Refuses the first two connections, like a compute that is still resuming."""

        def connect(self) -> Any:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ConnectionRefusedError("compute is resuming")
            return real.connect()

        async def dispose(self) -> None:
            await real.dispose()

    repo._engine = Flaky()  # type: ignore[assignment]
    try:
        assert await repo.ping(attempts=4, delay_s=0.0) is True
        assert attempts == 3
    finally:
        await repo.close()


def test_database_ping_returns_true_when_reachable(tmp_path: Path) -> None:
    import asyncio

    from llmflow.storage.usage import UsageRepo

    async def run() -> bool:
        repo = UsageRepo(f"sqlite+aiosqlite:///{tmp_path}/ping.db")
        try:
            return await repo.ping()
        finally:
            await repo.close()

    assert asyncio.run(run()) is True
