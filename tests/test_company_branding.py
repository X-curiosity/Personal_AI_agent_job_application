from __future__ import annotations

import pytest

from tau_job_application.company_branding import (
    CompanyBrandStore,
    normalize_company_name,
    validate_public_https_logo_url,
)


def test_brand_mapping_is_normalized_persisted_and_updatable(tmp_path, monkeypatch) -> None:
    database = tmp_path / "local.sqlite"
    store = CompanyBrandStore(database)
    moments = iter(("2026-10-06T10:00:00+00:00", "2026-10-06T10:05:00+00:00"))
    monkeypatch.setattr(store, "_now", lambda: next(moments))

    created = store.upsert(
        "  Figma\t",
        "https://assets.example.test/figma.svg",
        source="candidate-provided",
    )
    updated = store.upsert("FIGMA", None, source="candidate choice")

    assert created.company_name == "Figma"
    assert created.normalized_name == "figma"
    assert created.logo_url == "https://assets.example.test/figma.svg"
    assert updated.company_name == "FIGMA"
    assert updated.logo_url is None
    assert updated.source == "candidate choice"
    assert updated.created_at == "2026-10-06T10:00:00+00:00"
    assert updated.updated_at == "2026-10-06T10:05:00+00:00"

    restored = CompanyBrandStore(database).get(" figma ")
    assert restored == updated
    assert [brand.company_name for brand in store.list_brands()] == ["FIGMA"]
    # A deliberate no-logo mapping suppresses any future curated fallback.
    assert store.logo_for("Figma") is None


@pytest.mark.parametrize(
    "value",
    [
        "http://assets.example.test/logo.svg",
        "data:image/svg+xml,<svg></svg>",
        "javascript:alert(1)",
        "https://person:secret@assets.example.test/logo.svg",
        "https://@assets.example.test/logo.svg",
        "https:///logo.svg",
        "https://localhost/logo.svg",
        "https://127.0.0.1/logo.svg",
    ],
)
def test_logo_url_validation_rejects_unsafe_or_non_public_urls(value: str) -> None:
    with pytest.raises(ValueError, match="public HTTPS URL"):
        validate_public_https_logo_url(value)


def test_logo_url_validation_accepts_a_public_https_url_and_optional_blank_value() -> None:
    assert validate_public_https_logo_url(" https://assets.example.test/brand.svg?version=2 ") == (
        "https://assets.example.test/brand.svg?version=2"
    )
    assert validate_public_https_logo_url("") is None
    assert validate_public_https_logo_url(None) is None


def test_brand_deletion_and_company_name_validation(tmp_path) -> None:
    store = CompanyBrandStore(tmp_path / "local.sqlite")
    store.upsert("Mistral AI", "https://assets.example.test/mistral.svg")

    assert store.delete("  mistral ai ") is True
    assert store.get("Mistral AI") is None
    assert store.delete("Mistral AI") is False
    assert normalize_company_name("  MISTRAL\nAI  ") == "mistral ai"
    with pytest.raises(ValueError, match="Company name"):
        normalize_company_name("   ")
