from __future__ import annotations

import pytest

from tau_job_application.computer_use import ComputerUseError, OpenAIResponsesComputerUse
from tau_job_application.computer_use_providers import (
    TauComputerUseProviderConfig,
    create_tau_computer_use,
    probe_tau_computer_use_access,
)


class Object:
    def __init__(self, **values):
        self.__dict__.update(values)


@pytest.mark.parametrize("values", [
    {"api_key": "", "base_url": "https://api.example.com/v1", "model": "computer-model"},
    {"api_key": "key", "base_url": "http://api.example.com/v1", "model": "computer-model"},
    {"api_key": "key", "base_url": "https://user:pass@api.example.com/v1", "model": "computer-model"},
    {"api_key": "key", "base_url": "https://api.example.com/v1", "model": ""},
])
def test_provider_config_rejects_unsafe_or_empty_values(values):
    with pytest.raises(ComputerUseError):
        TauComputerUseProviderConfig(**values)


def test_factory_uses_validated_tau_compatible_credentials():
    calls = []
    client = Object(responses=Object())
    config = TauComputerUseProviderConfig(
        api_key=" secret ", base_url="https://tau.example.com/v1/", model=" computer-use-model "
    )
    adapter = create_tau_computer_use(
        config, client_factory=lambda **kwargs: calls.append(kwargs) or client
    )
    assert isinstance(adapter, OpenAIResponsesComputerUse)
    assert adapter.model == "computer-use-model"
    assert calls == [{"api_key": "secret", "base_url": "https://tau.example.com/v1"}]
    tau_config = config.tau_config()
    assert tau_config.api_key == "secret"
    assert tau_config.base_url == "https://tau.example.com/v1"


def test_non_billable_probe_only_retrieves_model_metadata():
    calls = []
    client = Object(
        responses=Object(create=lambda **_: pytest.fail("probe must not run inference")),
        models=Object(retrieve=lambda model: calls.append(model) or Object(id=model)),
    )
    config = TauComputerUseProviderConfig("key", "https://tau.example.com/v1", "computer-use-model")
    report = probe_tau_computer_use_access(config, client_factory=lambda **_: client)
    assert report.available
    assert calls == ["computer-use-model"]
    assert "does not" not in report.detail.lower()
    assert "verified only" in report.detail.lower()


def test_probe_reports_denied_model_without_claiming_compatibility():
    def denied(_model):
        raise RuntimeError("model not found")

    client = Object(responses=Object(), models=Object(retrieve=denied))
    config = TauComputerUseProviderConfig("key", "https://tau.example.com/v1", "chat-model")
    report = probe_tau_computer_use_access(config, client_factory=lambda **_: client)
    assert not report.available
    assert "RuntimeError" in report.detail
    assert "model not found" not in report.detail
