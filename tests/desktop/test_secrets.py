from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from bluewhale_agent.config import Settings
from bluewhale_agent.desktop.secrets import (
    KeyringSecretStore,
    MemorySecretStore,
    SecretStoreError,
    build_desktop_provider_factory,
)
from bluewhale_agent.domain.models import Message, ModelResponse


class FakeBackend:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.fail = False

    def get_password(self, service: str, account: str) -> str | None:
        if self.fail:
            raise RuntimeError("backend details")
        return self.values.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        if self.fail:
            raise RuntimeError(f"backend rejected {value}")
        self.values[(service, account)] = value

    def delete_password(self, service: str, account: str) -> None:
        if self.fail:
            raise RuntimeError("backend details")
        self.values.pop((service, account), None)


class CapturingProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def complete(
        self, _messages: list[Message], _tools: list[dict[str, object]]
    ) -> ModelResponse:
        return ModelResponse(content="unused", finish_reason="stop")


def base_settings(api_key: str | None = None) -> Settings:
    return Settings.model_construct(
        deepseek_api_key=SecretStr(api_key) if api_key else None,
        model="test-model",
        base_url="https://api.deepseek.com",
        workspace=Path.cwd(),
        limits=Settings().limits,
    )


def test_memory_secret_store_never_exposes_value_in_repr() -> None:
    store = MemorySecretStore()
    store.set_api_key("unit-test-secret-value")

    assert store.has_api_key() is True
    assert store.get_api_key() == "unit-test-secret-value"
    assert "unit-test-secret-value" not in repr(store)

    store.clear_api_key()
    assert store.get_api_key() is None


def test_keyring_store_uses_fixed_service_and_normalizes_value() -> None:
    backend = FakeBackend()
    store = KeyringSecretStore(backend)

    store.set_api_key("  new-key  ")

    assert backend.values[(store.SERVICE, store.ACCOUNT)] == "new-key"
    assert store.get_api_key() == "new-key"
    store.clear_api_key()
    assert store.has_api_key() is False


def test_secret_store_rejects_blank_and_sanitizes_backend_failures() -> None:
    backend = FakeBackend()
    store = KeyringSecretStore(backend)
    with pytest.raises(SecretStoreError, match="cannot be empty"):
        store.set_api_key("   ")

    backend.fail = True
    with pytest.raises(SecretStoreError, match="Unable to access macOS Keychain") as error:
        store.set_api_key("sensitive-test-value")
    assert "sensitive-test-value" not in str(error.value)
    assert "backend" not in str(error.value)


def test_provider_factory_prefers_keychain_then_environment_settings() -> None:
    store = MemorySecretStore()
    store.set_api_key("keychain-value")
    factory = build_desktop_provider_factory(
        store,
        base_settings("environment-value"),
        provider_builder=CapturingProvider,
    )

    provider = factory()

    assert isinstance(provider, CapturingProvider)
    assert provider.settings.deepseek_api_key is not None
    assert provider.settings.deepseek_api_key.get_secret_value() == "keychain-value"

    store.clear_api_key()
    fallback = factory()
    assert isinstance(fallback, CapturingProvider)
    assert fallback.settings.deepseek_api_key is not None
    assert fallback.settings.deepseek_api_key.get_secret_value() == "environment-value"


def test_provider_factory_rejects_missing_key() -> None:
    factory = build_desktop_provider_factory(
        MemorySecretStore(),
        base_settings(),
        provider_builder=CapturingProvider,
    )

    with pytest.raises(ValueError, match="not configured"):
        factory()
