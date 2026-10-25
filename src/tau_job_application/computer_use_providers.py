"""Validated provider setup for Responses computer use.

These helpers are suitable for CLI/UI integration and never contact an employer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit

from tau_ai import OpenAICompatibleConfig

from tau_job_application.computer_use import ComputerUseError, OpenAIResponsesComputerUse


@dataclass(frozen=True)
class ComputerUseProviderReport:
    """Non-billable provider/model access result for display by a CLI or UI."""

    available: bool
    model: str
    base_url: str
    detail: str


@dataclass(frozen=True)
class TauComputerUseProviderConfig:
    """Tau-compatible credentials plus the explicit Responses computer-use model."""

    api_key: str
    base_url: str
    model: str

    def __post_init__(self) -> None:
        key = self.api_key.strip() if isinstance(self.api_key, str) else ""
        model = self.model.strip() if isinstance(self.model, str) else ""
        base_url = self.base_url.strip() if isinstance(self.base_url, str) else ""
        parsed = urlsplit(base_url)
        if not key:
            raise ComputerUseError("Computer-use provider API key is required")
        if not model:
            raise ComputerUseError("Computer-use model is required")
        if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ComputerUseError("Computer-use provider base URL must be HTTPS without credentials")
        object.__setattr__(self, "api_key", key)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "base_url", base_url.rstrip("/"))

    def tau_config(self) -> OpenAICompatibleConfig:
        """Return the same provider configuration used by the Tau agent stack."""
        return OpenAICompatibleConfig(api_key=self.api_key, base_url=self.base_url)


def create_tau_computer_use(
    config: TauComputerUseProviderConfig,
    *,
    client_factory: Callable[..., Any] | None = None,
) -> OpenAIResponsesComputerUse:
    """Build an OpenAI Responses adapter from validated Tau-compatible settings."""
    # Construct this eagerly so configuration drift from Tau's provider contract fails clearly.
    config.tau_config()
    if client_factory is None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ComputerUseError("Install the optional 'openai' package to use computer use") from exc
        client_factory = OpenAI
    client = client_factory(api_key=config.api_key, base_url=config.base_url)
    return OpenAIResponsesComputerUse(client=client, model=config.model)


def probe_tau_computer_use_access(
    config: TauComputerUseProviderConfig,
    *,
    client_factory: Callable[..., Any] | None = None,
) -> ComputerUseProviderReport:
    """Check model visibility with the non-generative Models API; no billable inference is made.

    A successful lookup proves credential/model visibility only. It deliberately does not claim
    that a chat-completions model supports the Responses computer-use tool.
    """
    adapter = create_tau_computer_use(config, client_factory=client_factory)
    try:
        found = adapter.client.models.retrieve(config.model)
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        suffix = f" (HTTP {status})" if status else ""
        return ComputerUseProviderReport(False, config.model, config.base_url, f"Model access probe failed: {type(exc).__name__}{suffix}")
    model_id = getattr(found, "id", None) or config.model
    return ComputerUseProviderReport(
        True,
        str(model_id),
        config.base_url,
        "Model is visible; Responses computer-use support is verified only when an actual run starts.",
    )
