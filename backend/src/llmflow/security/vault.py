"""Encryption of tenants' provider API keys at rest.

Fernet (AES-128-CBC + HMAC-SHA256, authenticated). The plaintext is wrapped in JSON that
includes the tenant id and provider, and both are verified after decryption, so a ciphertext
copied between rows (or tenants) is rejected. ``master_keys`` may hold several keys: the
first encrypts, all decrypt, which allows rotation without re-encrypting everything at once.
"""

from __future__ import annotations

import json

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class VaultError(ValueError):
    pass


class KeyVault:
    def __init__(self, master_keys: list[str]) -> None:
        if not master_keys:
            raise VaultError("no master key configured")
        try:
            self._fernet = MultiFernet([Fernet(k.encode()) for k in master_keys])
        except (ValueError, TypeError) as exc:
            raise VaultError(
                "LLMFLOW_MASTER_KEY is not a valid Fernet key; generate one with: "
                "python -c 'from cryptography.fernet import Fernet;"
                "print(Fernet.generate_key().decode())'"
            ) from exc

    def encrypt(self, tenant_id: str, provider: str, secret: str) -> str:
        payload = json.dumps({"t": tenant_id, "p": provider, "k": secret}, separators=(",", ":"))
        return self._fernet.encrypt(payload.encode()).decode()

    def rotate(self, token: str) -> str:
        """Re-encrypt ``token`` under the primary (first) master key without exposing the
        plaintext. Used by the rotation tool after a new key is prepended to the list."""
        try:
            return self._fernet.rotate(token.encode()).decode()
        except InvalidToken as exc:
            raise VaultError("stored key cannot be decrypted (wrong master key?)") from exc

    def decrypt(self, tenant_id: str, provider: str, token: str) -> str:
        try:
            data = json.loads(self._fernet.decrypt(token.encode()))
        except (InvalidToken, ValueError) as exc:
            raise VaultError("stored key cannot be decrypted (wrong master key?)") from exc
        if data.get("t") != tenant_id or data.get("p") != provider:
            raise VaultError("stored key does not belong to this tenant/provider")
        secret = data.get("k")
        if not isinstance(secret, str):
            raise VaultError("stored key is malformed")
        return secret
