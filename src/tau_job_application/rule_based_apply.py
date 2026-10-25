"""Deterministic, local job-application form filling with explicit final approval.

This module deliberately contains no model or provider integration.  It fills only
values supplied by the caller and reuses the hardened browser/network submission
boundary from :mod:`tau_job_application.computer_use`.
"""

from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .computer_use import (
    ApprovalCallback,
    ComputerUseError,
    RunOutcome,
    _ControlledConnectProxy,
    _INTERCEPT_SCRIPT,
    _NetworkGuard,
    _page_block_reason,
    _playwright_browser,
    _prepare_cv_upload,
    submit_fingerprint,
    validate_public_https_url,
)


@dataclass(frozen=True)
class RuleBasedApplyConfig:
    """All data the rule-based runner is permitted to put into a form."""

    job_url: str
    application_id: str
    form_selector: str = "form"
    full_name: str = ""
    email: str = ""
    phone: str = ""
    skills: str | Sequence[str] = ""
    links: Mapping[str, str] = field(default_factory=dict)
    location: str = ""
    custom_answers: Mapping[str, str | bool] = field(default_factory=dict)
    cv_file_path: str | None = None
    cv_file_bytes: bytes | None = None
    cv_file_name: str = "cv.pdf"
    cv_required: bool = False
    allow_json_submission: bool = False
    max_actions: int = 60
    timeout_seconds: float = 180.0


_SCAN_SCRIPT = r"""
(selector) => {
  const root = document.querySelector(selector || 'form');
  if (!root) return {fields: [], submits: []};
  const visible = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
  const text = e => (e && (e.innerText || e.textContent) || '').trim().replace(/\s+/g, ' ');
  const label = e => {
    if (e.labels && e.labels.length) return Array.from(e.labels).map(text).filter(Boolean).join(' ');
    const wrapping = e.closest && e.closest('label');
    return text(wrapping) || e.getAttribute('aria-label') || e.getAttribute('placeholder') || e.name || e.id || '';
  };
  let n = 0;
  const fields = Array.from(root.querySelectorAll('input, textarea, select')).filter(e => !e.disabled && visible(e)).map(e => {
    const selector = `tau-rule-${++n}`; e.setAttribute('data-tau-rule', selector);
    return {
      selector: `[data-tau-rule="${selector}"]`, tag: e.tagName.toLowerCase(),
      type: (e.type || '').toLowerCase(), name: e.name || '', label: label(e),
      required: !!e.required, value: e.value || '', checked: !!e.checked,
      options: e.tagName === 'SELECT' ? Array.from(e.options).map(o => ({label: text(o), value: o.value, disabled: o.disabled})) : []
    };
  });
  const submits = Array.from(root.querySelectorAll('button, input[type=submit], input[type=image]'))
    .filter(e => !e.disabled && visible(e)).map(e => {
      const selector = `tau-rule-${++n}`; e.setAttribute('data-tau-rule', selector);
      return {selector: `[data-tau-rule="${selector}"]`, label: text(e) || e.value || e.name || e.id || ''};
    });
  return {fields, submits};
}
"""

_NAME_ALIASES = {"full name", "name", "candidate name", "legal name", "your name"}
_EMAIL_ALIASES = {"email", "email address", "e mail", "your email"}
_PHONE_ALIASES = {"phone", "phone number", "telephone", "mobile", "mobile number"}
_SKILL_ALIASES = {"skills", "key skills", "technical skills", "skill set"}
_LOCATION_ALIASES = {"location", "current location", "city", "city and state", "address"}
_LINK_HINTS = ("linkedin", "github", "portfolio", "website", "personal site", "url")
_CV_HINTS = ("resume", "résumé", "cv", "curriculum vitae")
_CONSENT_HINTS = ("consent", "agree", "privacy", "terms", "authorize", "certify", "acknowledge")


def validate_custom_answers(value: Mapping[str, Any]) -> dict[str, str | bool]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) or not isinstance(answer, (str, bool)) for key, answer in value.items()):
        raise ValueError("Custom answers must be a JSON object of label:string/boolean values.")
    return dict(value)


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").replace("-", " ").split())


def _answer_for(field: Mapping[str, Any], config: RuleBasedApplyConfig) -> tuple[bool, str | bool]:
    label, name = _norm(field.get("label")), _norm(field.get("name"))
    custom = {_norm(key): value for key, value in config.custom_answers.items()}
    if label in custom:  # custom answers intentionally require an exact normalized label
        return True, custom[label]
    keys = {label, name}
    if keys & _NAME_ALIASES and config.full_name: return True, config.full_name
    if keys & _EMAIL_ALIASES and config.email: return True, config.email
    if keys & _PHONE_ALIASES and config.phone: return True, config.phone
    if keys & _SKILL_ALIASES and config.skills:
        return True, ", ".join(config.skills) if not isinstance(config.skills, str) else config.skills
    if keys & _LOCATION_ALIASES and config.location: return True, config.location
    for link_name, link_value in config.links.items():
        if link_value and (_norm(link_name) in keys or _norm(link_name) == label): return True, link_value
    if field.get("type") == "url" and len(config.links) == 1:
        return True, next(iter(config.links.values()))
    return False, ""


def _choose_option(options: Sequence[Mapping[str, Any]], answer: str) -> str | None:
    wanted = _norm(answer)
    matches = [str(option["value"]) for option in options if not option.get("disabled") and _norm(option.get("label")) == wanted]
    return matches[0] if len(matches) == 1 else None


class RuleBasedApplyRunner:
    """Fill one fresh visible browser form and submit it at most once."""

    def run(
        self,
        config: RuleBasedApplyConfig,
        *,
        approve_submit: ApprovalCallback,
        browser_factory: Callable[[], Any] | None = None,
        resolver: Callable[..., Any] = socket.getaddrinfo,
        cancel_event: Any | None = None,
    ) -> RunOutcome:
        validate_public_https_url(config.job_url)
        if not config.application_id:
            raise ComputerUseError("application_id is required")
        validate_custom_answers(config.custom_answers)
        if config.max_actions < 1 or config.timeout_seconds <= 0:
            raise ComputerUseError("Action and time bounds must be positive")
        cv = _prepare_cv_upload(config.cv_file_path, config.cv_file_bytes, config.cv_file_name)
        cancelled = lambda: bool(cancel_event is not None and cancel_event.is_set())
        if cancelled(): return RunOutcome("cancelled", "Cancelled by user")

        proxy: _ControlledConnectProxy | None = None
        if browser_factory is None:
            proxy = _ControlledConnectProxy(resolver); proxy.start()
            try: browser = _playwright_browser(proxy.url)
            except Exception:
                proxy.close(); raise
        else:
            browser = browser_factory()
        context = None
        started, actions = time.monotonic(), 0
        try:
            context = browser.new_context(viewport={"width": 1024, "height": 768})
            network = _NetworkGuard(config.application_id, approve_submit, resolver)
            context.route("**/*", network.handle)
            context.on("response", network.observe_response)
            context.on("requestfailed", network.observe_request_failed)
            context.add_init_script(_INTERCEPT_SCRIPT)
            page = context.new_page()
            try: page.goto(config.job_url, wait_until="domcontentloaded")
            except Exception:
                if network.blocked_reason: return RunOutcome("blocked", network.blocked_reason)
                raise
            if network.blocked_reason: return RunOutcome("blocked", network.blocked_reason)
            reason = _page_block_reason(page)
            if reason: return RunOutcome("blocked", reason)
            snapshot = page.evaluate(_SCAN_SCRIPT, config.form_selector)
            fields, review = snapshot.get("fields", []), {}
            cv_attached = False
            labels_seen: dict[str, int] = {}
            for item in fields:
                label = _norm(item.get("label"))
                if label: labels_seen[label] = labels_seen.get(label, 0) + 1
            for field_info in fields:
                if cancelled(): return RunOutcome("cancelled", "Cancelled by user", actions)
                if time.monotonic() - started >= config.timeout_seconds: return RunOutcome("blocked", "Time limit reached", actions)
                kind = field_info.get("type", "")
                if kind in {"hidden", "submit", "button", "image", "reset"}: continue
                label = str(field_info.get("label") or field_info.get("name") or "unlabelled field")
                normalized = _norm(label)
                if labels_seen.get(normalized, 0) > 1 and normalized in {_norm(k) for k in config.custom_answers}:
                    return RunOutcome("blocked", f"Ambiguous field label: {label}", actions)
                locator = page.locator(field_info["selector"])
                if kind == "file":
                    if not any(hint in normalized for hint in _CV_HINTS):
                        if field_info.get("required"): return RunOutcome("blocked", f"Unknown required file field: {label}", actions)
                        continue
                    if cv is None: return RunOutcome("blocked", "CV file is required by the form", actions)
                    locator.set_input_files(cv["playwright"]); actions += 1
                    review[label] = cv["identity"]["cv_file_name"]
                    cv_attached = True
                    continue
                found, answer = _answer_for(field_info, config)
                if kind in {"checkbox", "radio"}:
                    if any(marker in normalized for marker in _CONSENT_HINTS):
                        return RunOutcome("blocked", f"Consent field requires manual handling: {label}", actions)
                    if not found:
                        if field_info.get("required"): return RunOutcome("blocked", f"Unknown required field: {label}", actions)
                        continue
                    truthy = answer is True or _norm(answer) in {"yes", "true", "checked", "1", normalized}
                    if not truthy: return RunOutcome("blocked", f"Checkbox/radio answer is not an exact affirmative choice: {label}", actions)
                    locator.check(); actions += 1; review[label] = "checked"
                elif field_info.get("tag") == "select":
                    if not found:
                        if field_info.get("required"): return RunOutcome("blocked", f"Unknown required field: {label}", actions)
                        continue
                    option = _choose_option(field_info.get("options", []), str(answer))
                    if option is None: return RunOutcome("blocked", f"Answer does not exactly match one option: {label}", actions)
                    locator.select_option(option); actions += 1; review[label] = str(answer)
                elif kind in {"text", "email", "tel", "url", "search", ""} or field_info.get("tag") == "textarea":
                    if not found:
                        if field_info.get("required"): return RunOutcome("blocked", f"Unknown required field: {label}", actions)
                        continue
                    locator.fill(str(answer)); actions += 1; review[label] = str(answer)
                elif field_info.get("required"):
                    return RunOutcome("blocked", f"Unsupported required field: {label}", actions)
                if actions > config.max_actions: return RunOutcome("blocked", "Action limit reached", actions)
            if config.cv_required and (cv is None or not cv_attached):
                return RunOutcome("blocked", "No supported CV upload field matched; the CV was not attached", actions)
            if not snapshot.get("submits") or len(snapshot["submits"]) != 1:
                return RunOutcome("blocked", "A single unambiguous submit control is required", actions)
            if not review: return RunOutcome("blocked", "No caller-supplied values matched the form", actions)
            page.locator(snapshot["submits"][0]["selector"]).click(); actions += 1
            pending = page.evaluate("window.__tauSubmitGuard && window.__tauSubmitGuard.take()")
            if not pending: return RunOutcome("blocked", "Submit control did not produce a verifiable submission", actions)
            if pending.get("valid") != "true": return RunOutcome("blocked", "Required fields failed browser validation", actions)
            if pending.get("submit_kind") == "json" and not config.allow_json_submission:
                return RunOutcome("blocked", "JSON submission was not explicitly armed", actions)
            reviewed = dict(pending)
            reviewed["review_values"] = json.dumps(review, sort_keys=True, ensure_ascii=True)
            if cv is not None and cv_attached: reviewed.update(cv["identity"])
            fingerprint = submit_fingerprint(config.application_id, reviewed)
            if not approve_submit(fingerprint, reviewed):
                return RunOutcome("cancelled" if cancelled() else "pending_approval", "Cancelled by user" if cancelled() else "Explicit submit approval required", actions, fingerprint)
            if page.evaluate("window.__tauSubmitGuard && window.__tauSubmitGuard.take()") != pending:
                return RunOutcome("blocked", "Submission details changed after approval", actions, fingerprint)
            network.arm_submission(reviewed, fingerprint)
            if not page.evaluate("window.__tauSubmitGuard.approve()"):
                return RunOutcome("blocked", "Submission target changed before approval", actions, fingerprint)
            for _ in range(50):
                if network.blocked_reason or network.confirmed: break
                if cancelled(): return RunOutcome("submission_unknown", "Stop requested after submission release; verify with the employer before retrying", actions, fingerprint)
                page.wait_for_timeout(100)
            if network.confirmed: return RunOutcome("submitted", "Approved submission received a successful response", actions, fingerprint)
            if network.blocked_reason: return RunOutcome("blocked", network.blocked_reason, actions, fingerprint)
            return RunOutcome("submission_unknown", "Submission was released but no HTTP response was confirmed; verify before retrying", actions, fingerprint)
        finally:
            if context is not None: context.close()
            browser.close()
            if proxy is not None: proxy.close()


def run(config: RuleBasedApplyConfig, **kwargs: Any) -> RunOutcome:
    """Streamlit-friendly convenience entry point."""
    return RuleBasedApplyRunner().run(config, **kwargs)
