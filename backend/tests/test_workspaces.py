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
PASSWORD = "correct horse battery"


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
            "/auth/signup", json={**base, "email": "bob@example.com", "password": "bobbobbobbob1"}
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
                            json={"current_password": "wrong", "new_password": "a brand new passphrase"})  # fmt: skip
        assert bad.status_code == 403
        ok = p.client.post("/auth/change-password", headers=p.h,
                           json={"current_password": PASSWORD, "new_password": "a brand new passphrase"})  # fmt: skip
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
                                                 "password": "a brand new passphrase"}).status_code == 200  # fmt: skip


def test_recovery_code_resets_password_once(env: Env, people: list[Person]) -> None:
    p = person(env, people)
    body = {
        "email": "alice@example.com",
        "recovery_code": p.codes[0],
        "new_password": "recovered passphrase 1",
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
                                               "password": "recovered passphrase 1"}).status_code == 200  # fmt: skip


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


def test_deleting_a_provider_key_stops_routing(env: Env, people: list[Person]) -> None:
    p = person(env, people)
    save_key(p, "p1", "tenant-key-AAAAAAAA1111")
    assert env.c.post("/v1/chat/completions", headers=p.bearer, json=BODY).status_code == 200
    assert p.client.delete("/account/provider-keys/p1", headers=p.h).status_code == 200
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
    for bad in ("short", "a" * 20, "password123456", "x" * 200):
        with pytest.raises(pw.PasswordPolicyError):
            pw.check_policy(bad)
    with pytest.raises(pw.PasswordPolicyError):
        pw.check_policy("alicealice1234", "alice@example.com")
    pw.check_policy("correct horse battery")
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
