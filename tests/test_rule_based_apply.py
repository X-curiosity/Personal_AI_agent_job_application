import json

import pytest

from tau_job_application.computer_use import ComputerUseError
from tau_job_application.rule_based_apply import RuleBasedApplyConfig, run


PUBLIC = lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))]


class Request:
    url = "https://jobs.example.com/apply"
    method = "POST"
    resource_type = "document"

    def __init__(self, pending):
        self.post_data = pending.get("json_body") or "full_name=Ada+Lovelace&email=ada%40example.com"
        self.content_type = "application/json" if pending.get("submit_kind") == "json" else "application/x-www-form-urlencoded"

    def header_value(self, name):
        return self.content_type if name == "content-type" else None


class Route:
    def __init__(self): self.released = False
    def continue_(self): self.released = True
    def abort(self, _reason): self.released = False


class Locator:
    def __init__(self, page, selector): self.page, self.selector = page, selector
    def inner_text(self, timeout=None): return self.page.body
    def fill(self, value): self.page.values[self.selector] = value
    def check(self): self.page.values[self.selector] = "checked"
    def select_option(self, value): self.page.values[self.selector] = value
    def set_input_files(self, value): self.page.values[self.selector] = value
    def click(self): self.page.clicked = self.selector


class Page:
    frames = ()

    def __init__(self, context, scan, pending):
        self.context, self.scan, self.pending = context, scan, pending
        self.body, self.values, self.clicked = "Application form", {}, None
    def goto(self, *args, **kwargs): pass
    def locator(self, selector): return Locator(self, selector)
    def evaluate(self, script, _selector=None):
        if "const visible" in script: return self.scan
        if "take()" in script: return self.pending
        if "approve()" in script:
            request, route = Request(self.pending), Route()
            self.context.route_handler(route, request)
            if route.released:
                response = type("Response", (), {"request": request, "status": 200})()
                self.context.listeners["response"](response)
            self.pending = None
            return route.released
        raise AssertionError(script)
    def wait_for_timeout(self, _ms): pass


class Context:
    def __init__(self, scan, pending): self.scan, self.pending, self.listeners = scan, pending, {}
    def route(self, _pattern, handler): self.route_handler = handler
    def on(self, event, callback): self.listeners[event] = callback
    def add_init_script(self, _script): pass
    def new_page(self): self.page = Page(self, self.scan, self.pending); return self.page
    def close(self): pass


class Browser:
    def __init__(self, scan, pending): self.context = Context(scan, pending)
    def new_context(self, **kwargs): return self.context
    def close(self): pass


def field(selector, label, *, name="", kind="text", required=True, tag="input", options=()):
    return {"selector": selector, "label": label, "name": name, "type": kind,
            "required": required, "tag": tag, "options": list(options)}


def form(fields):
    return {"fields": fields, "submits": [{"selector": "#submit", "label": "Apply"}]}


def pending(**extra):
    value = {"action": "https://jobs.example.com/apply", "method": "post", "button_text": "Apply",
             "page_url": "https://jobs.example.com/apply", "valid": "true",
             "fields": json.dumps([["full_name", "Ada Lovelace"], ["email", "ada@example.com"]])}
    value.update(extra)
    return value


def config(**changes):
    values = dict(job_url="https://jobs.example.com/apply", application_id="app-1",
                  full_name="Ada Lovelace", email="ada@example.com")
    values.update(changes)
    return RuleBasedApplyConfig(**values)


def test_fills_only_explicit_values_reviews_them_and_submits_once():
    browser = Browser(form([
        field("#name", "Full name", name="full_name"),
        field("#email", "Email", name="email", kind="email"),
        field("#optional", "Why us?", required=False, tag="textarea"),
    ]), pending())
    reviewed = {}
    outcome = run(config(), browser_factory=lambda: browser, resolver=PUBLIC,
                  approve_submit=lambda fp, details: reviewed.update(details) or True)
    assert outcome.status == "submitted"
    assert browser.context.page.values == {"#name": "Ada Lovelace", "#email": "ada@example.com"}
    assert json.loads(reviewed["review_values"]) == {"Email": "ada@example.com", "Full name": "Ada Lovelace"}
    assert outcome.submit_fingerprint


def test_unknown_required_field_blocks_without_submit():
    browser = Browser(form([field("#name", "Full name"), field("#salary", "Expected salary")]), pending())
    outcome = run(config(), browser_factory=lambda: browser, resolver=PUBLIC, approve_submit=lambda *_: True)
    assert outcome.status == "blocked"
    assert "Unknown required field" in outcome.reason
    assert browser.context.page.clicked is None


def test_custom_answers_require_unambiguous_exact_label_and_select_option():
    options = [{"label": "Yes", "value": "yes", "disabled": False}, {"label": "No", "value": "no", "disabled": False}]
    browser = Browser(form([field("#work", "Authorized to work?", tag="select", kind="select-one", options=options)]), pending())
    outcome = run(config(custom_answers={"Authorized to work?": "Maybe"}), browser_factory=lambda: browser,
                  resolver=PUBLIC, approve_submit=lambda *_: True)
    assert outcome.status == "blocked"
    assert "exactly match" in outcome.reason


def test_consent_and_captcha_are_never_auto_handled():
    consent_browser = Browser(form([field("#agree", "I agree to privacy terms", kind="checkbox")]), pending())
    outcome = run(config(custom_answers={"I agree to privacy terms": True}), browser_factory=lambda: consent_browser,
                  resolver=PUBLIC, approve_submit=lambda *_: True)
    assert outcome.status == "blocked" and "Consent" in outcome.reason

    captcha_browser = Browser(form([field("#name", "Full name")]), pending())
    captcha_browser.context.page = None
    original_new_page = captcha_browser.context.new_page
    def new_page():
        page = original_new_page(); page.body = "Verify you are human CAPTCHA"; return page
    captcha_browser.context.new_page = new_page
    outcome = run(config(), browser_factory=lambda: captcha_browser, resolver=PUBLIC, approve_submit=lambda *_: True)
    assert outcome.status == "blocked" and "CAPTCHA" in outcome.reason


def test_json_requires_explicit_arming_and_declined_approval_does_not_release():
    json_pending = pending(submit_kind="json", json_body='{"email":"ada@example.com"}', fields="[]")
    browser = Browser(form([field("#name", "Full name")]), json_pending)
    outcome = run(config(), browser_factory=lambda: browser, resolver=PUBLIC, approve_submit=lambda *_: True)
    assert outcome.status == "blocked" and "explicitly armed" in outcome.reason

    browser = Browser(form([field("#name", "Full name")]), json_pending)
    outcome = run(config(allow_json_submission=True), browser_factory=lambda: browser,
                  resolver=PUBLIC, approve_submit=lambda *_: True)
    assert outcome.status == "submitted"

    browser = Browser(form([field("#name", "Full name")]), pending())
    outcome = run(config(), browser_factory=lambda: browser, resolver=PUBLIC, approve_submit=lambda *_: False)
    assert outcome.status == "pending_approval"
    assert browser.context.page.pending is not None


def test_custom_answer_values_are_strictly_validated():
    from tau_job_application.rule_based_apply import validate_custom_answers
    assert validate_custom_answers({"Question": True, "Other": "yes"}) == {"Question": True, "Other": "yes"}
    for bad in (None, [], {"x": 1}, {"x": None}, {1: "yes"}):
        with pytest.raises(ValueError):
            validate_custom_answers(bad)


def test_cv_required_also_blocks_when_no_cv_was_supplied():
    browser = Browser(form([field("#name", "Full name")]), pending())
    outcome = run(config(cv_required=True), browser_factory=lambda: browser, resolver=PUBLIC, approve_submit=lambda *_: True)
    assert outcome.status == "blocked"
    assert "CV was not attached" in outcome.reason


def test_cv_required_blocks_when_form_has_no_upload_field():
    browser = Browser(form([field("#name", "Full name")]), pending())
    outcome = run(config(cv_file_bytes=b"cv", cv_file_name="cv.pdf", cv_required=True), browser_factory=lambda: browser, resolver=PUBLIC, approve_submit=lambda *_: True)
    assert outcome.status == "blocked"
    assert "CV was not attached" in outcome.reason


def test_cv_bytes_are_attached_and_identity_is_reviewed():
    fields = [field("#name", "Full name"), field("#cv", "Resume", name="resume", kind="file")]
    browser = Browser(form(fields), pending())
    reviewed = {}
    outcome = run(config(cv_file_bytes=b"exact cv", cv_file_name="ada.pdf"), browser_factory=lambda: browser,
                  resolver=PUBLIC, approve_submit=lambda fp, details: reviewed.update(details) or False)
    assert outcome.status == "pending_approval"
    assert browser.context.page.values["#cv"]["buffer"] == b"exact cv"
    assert reviewed["cv_file_name"] == "ada.pdf"


def test_configuration_is_bounded_and_validated():
    with pytest.raises(ComputerUseError, match="bounds"):
        run(config(max_actions=0), browser_factory=lambda: None, approve_submit=lambda *_: False)
