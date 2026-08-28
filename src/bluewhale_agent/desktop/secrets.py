"""Secret storage adapters for the macOS desktop application."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Protocol, cast

from pydantic import SecretStr

from bluewhale_agent.config import Settings
from bluewhale_agent.providers.base import ModelProvider
from bluewhale_agent.providers.deepseek import DeepSeekProvider
from bluewhale_agent.web.sessions import ProviderFactory


class SecretStoreError(RuntimeError):
    """A sanitized failure while accessing secret storage."""


class SecretStore(Protocol):
    def has_api_key(self) -> bool: ...

    def get_api_key(self) -> str | None: ...

    def set_api_key(self, value: str) -> None: ...

    def clear_api_key(self) -> None: ...


class KeyringBackend(Protocol):
    def get_password(self, service: str, account: str) -> str | None: ...

    def set_password(self, service: str, account: str, value: str) -> None: ...

    def delete_password(self, service: str, account: str) -> None: ...


class MemorySecretStore:
    """Test-friendly secret store whose repr never reveals the value."""

    def __init__(self) -> None:
        self._api_key: SecretStr | None = None

    def has_api_key(self) -> bool:
        return self._api_key is not None

    def get_api_key(self) -> str | None:
        return self._api_key.get_secret_value() if self._api_key is not None else None

    def set_api_key(self, value: str) -> None:
        normalized = _normalize_key(value)
        self._api_key = SecretStr(normalized)

    def clear_api_key(self) -> None:
        self._api_key = None

    def __repr__(self) -> str:
        return f"MemorySecretStore(configured={self.has_api_key()})"


class KeyringSecretStore:
    """Persist the DeepSeek key in the current user's macOS Keychain."""

    SERVICE = "BlueWhale Coding Agent"
    ACCOUNT = "deepseek-api-key"

    def __init__(self, backend: KeyringBackend | None = None) -> None:
        if backend is None:
            try:
                backend = cast(KeyringBackend, importlib.import_module("keyring"))
            except ImportError as error:
                raise SecretStoreError("Desktop keyring support is not installed") from error
        self._backend = backend

    def has_api_key(self) -> bool:
        return self.get_api_key() is not None

    def get_api_key(self) -> str | None:
        try:
            return self._backend.get_password(self.SERVICE, self.ACCOUNT)
        except Exception as error:
            raise _keychain_error() from error

    def set_api_key(self, value: str) -> None:
        normalized = _normalize_key(value)
        try:
            self._backend.set_password(self.SERVICE, self.ACCOUNT, normalized)
        except Exception as error:
            raise _keychain_error() from error

    def clear_api_key(self) -> None:
        try:
            if self._backend.get_password(self.SERVICE, self.ACCOUNT) is not None:
                self._backend.delete_password(self.SERVICE, self.ACCOUNT)
        except Exception as error:
            raise _keychain_error() from error


ProviderBuilder = Callable[[Settings], ModelProvider]


def build_desktop_provider_factory(
    store: SecretStore,
    base: Settings,
    *,
    provider_builder: ProviderBuilder = DeepSeekProvider,
) -> ProviderFactory:
    """Build providers from the latest Keychain value for every run."""

    def factory() -> ModelProvider:
        stored_key = store.get_api_key()
        configured_key = base.deepseek_api_key
        api_key = stored_key or (
            configured_key.get_secret_value() if configured_key is not None else None
        )
        if not api_key:
            raise ValueError("DeepSeek API Key is not configured")
        settings = base.model_copy(update={"deepseek_api_key": SecretStr(api_key)})
        return provider_builder(settings)

    return factory


def _normalize_key(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise SecretStoreError("API Key cannot be empty")
    return normalized


def _keychain_error() -> SecretStoreError:
    return SecretStoreError("Unable to access macOS Keychain")
