from __future__ import annotations

import socket

import pytest

from tau_job_application.computer_use import (
    ComputerUseError,
    ComputerUseRunner,
    OpenAIResponsesComputerUse,
    submit_fingerprint,
    validate_action,
    validate_public_https_url,
    _ControlledConnectProxy,
    _NetworkGuard,
)


@pytest.mark.parametrize("url", [
    "http://jobs.example.com/1", "https://localhost/job", "https://127.0.0.1/job",
    "https://10.0.0.2/job", "https://user:secret@example.com/job", "https://example.com:8443/job",
])
def test_rejects_non_public_https_urls(url):
    with pytest.raises(ComputerUseError):
        validate_public_https_url(url)


def test_accepts_public_https_url():
    assert validate_public_https_url("https://jobs.example.com/openings/1") == "https://jobs.example.com/openings/1"


@pytest.mark.parametrize("action", [
    {"type": "shell", "command": "submit"},
    {"type": "click", "x": "4", "y": 2},
    {"type": "drag", "start_x": 1, "start_y": 2, "end_x": 3},
    {"type": "type", "text": ""},
    {"type": "click", "x": 1_000_000, "y": 0},
])
def test_action_validation_rejects_unsafe_or_malformed_actions(action):
    with pytest.raises(ComputerUseError):
        validate_action(action)


def test_accepts_current_openai_action_shapes():
    assert validate_action({"type": "scroll", "x": 10, "y": 20, "scroll_x": 0, "scroll_y": 400})["type"] == "scroll"
    assert validate_action({"type": "keypress", "keys": ["CTRL", "A"]})["keys"] == ["CTRL", "A"]
    assert validate_action({"type": "drag", "path": [{"x": 1, "y": 2}, {"x": 3, "y": 4}]})["type"] == "drag"
    assert validate_action({"type": "screenshot"})["type"] == "screenshot"
    assert validate_action({"type": "click", "x": 1, "y": 2, "button": "wheel", "keys": ["CTRL"]})["button"] == "wheel"
    with pytest.raises(ComputerUseError):
        validate_action({"type": "click", "x": 1, "y": 2, "button": "middle"})


def test_submit_fingerprint_is_stable_and_application_specific():
    details = {"action": "https://jobs.example.com/apply", "method": "post", "button_text": "Submit"}
    assert submit_fingerprint("a1", details) == submit_fingerprint("a1", dict(reversed(list(details.items()))))
    assert submit_fingerprint("a1", details) != submit_fingerprint("a2", details)


class FakeLocator:
    def __init__(self, page, selector): self.page, self.selector = page, selector
    def inner_text(self, timeout): return self.page.body
    def evaluate_all(self, expression): return self.page.unknown_required


class FakeMouse:
    def __init__(self, page): self.page = page
    def click(self, x, y, **kwargs): self.page.actions.append(("click", x, y))
    dblclick = click
    def move(self, x, y): self.page.actions.append(("move", x, y))
    def down(self): self.page.actions.append(("down",))
    def up(self): self.page.actions.append(("up",))
    def wheel(self, x, y): self.page.actions.append(("scroll", x, y))


class FakeKeyboard:
    def __init__(self, page): self.page = page
    def type(self, text): self.page.actions.append(("type", text))
    def press(self, keys): self.page.actions.append(("keypress", keys))


class FakePage:
    def __init__(self, *, body="Job application", pending=None, unknown_required=False):
        self.body, self.pending, self.unknown_required = body, pending, unknown_required
        self.actions = []; self.mouse = FakeMouse(self); self.keyboard = FakeKeyboard(self)
        self.approved = False; self.events = {}
    def on(self, event, handler): self.events[event] = handler
    def goto(self, *args, **kwargs): pass
    def screenshot(self, **kwargs): return b"private screenshot"
    def locator(self, selector): return FakeLocator(self, selector)
    def wait_for_timeout(self, ms): self.actions.append(("wait", ms))
    def evaluate(self, script):
        if "take()" in script: return self.pending
        if "approve()" in script: self.approved = True; return True
        raise AssertionError(script)


class FakeContext:
    def __init__(self, page): self.page = page; self.script = None; self.closed = False; self.routes = []; self.events = {}
    def route(self, pattern, handler): self.routes.append((pattern, handler))
    def on(self, event, handler): self.events[event] = handler
    def add_init_script(self, script): self.script = script
    def new_page(self): return self.page
    def close(self): self.closed = True


class FakeBrowser:
    def __init__(self, page): self.context = FakeContext(page); self.closed = False; self.context_calls = 0
    def new_context(self, **kwargs): self.context_calls += 1; self.context_options = kwargs; return self.context
    def close(self): self.closed = True


class FakeModel:
    def __init__(self, action): self.action = action; self.calls = []
    def next_action(self, **kwargs): self.calls.append(kwargs); return self.action


def run_with(page, model, **overrides):
    browser = FakeBrowser(page)
    runner = ComputerUseRunner(model, max_steps=overrides.pop("max_steps", 2))
    outcome = runner.run(
        job_url="https://jobs.example.com/1", application_id="app-1", instructions="Fill it",
        cv_text="secret CV", consent=overrides.pop("consent", lambda _: True),
        approve_submit=overrides.pop("approve_submit", lambda fp, details: False),
        browser_factory=lambda: browser,
        resolver=lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))],
        **overrides,
    )
    return outcome, browser


def test_requires_consent_before_browser_screenshot_or_cv_disclosure():
    model = FakeModel({"type": "done"})
    factory_called = False
    def factory():
        nonlocal factory_called; factory_called = True
    outcome = ComputerUseRunner(model).run(
        job_url="https://jobs.example.com/1", application_id="a", instructions="x", cv_text="secret",
        consent=lambda _: False, approve_submit=lambda *_: True, browser_factory=factory,
    )
    assert outcome.status == "pending_consent"
    assert not factory_called and not model.calls


def test_cancellation_between_actions_is_neutral_and_closes_browser():
    import threading
    cancel = threading.Event()
    class CancelModel:
        def next_action(self, **_kwargs):
            cancel.set()
            return {"type": "click", "x": 1, "y": 2}
    outcome, browser = run_with(FakePage(), CancelModel(), cancel_event=cancel)
    assert outcome.status == "cancelled"
    assert browser.context.closed and browser.closed


def test_cv_path_is_not_opened_before_data_sharing_consent():
    outcome = ComputerUseRunner(FakeModel({"type": "done"})).run(
        job_url="https://jobs.example.com/1", application_id="a", instructions="x", cv_text="secret",
        cv_file_path="/definitely/not/a/real/cv.pdf", consent=lambda _: False,
        approve_submit=lambda *_: True, browser_factory=lambda: pytest.fail("browser must not start"),
    )
    assert outcome.status == "pending_consent"


def test_blocks_captcha_before_sending_screenshot_to_model():
    model = FakeModel({"type": "done"})
    outcome, browser = run_with(FakePage(body="Please verify you are human CAPTCHA"), model)
    assert outcome.status == "blocked"
    assert not model.calls
    assert browser.context.closed and browser.closed


def test_blank_required_fields_do_not_block_filling_before_submit():
    outcome, _ = run_with(FakePage(unknown_required=True), FakeModel({"type": "done"}))
    assert outcome.status == "completed_without_submit"


def test_submit_is_intercepted_and_requires_explicit_fingerprint_approval():
    pending = {"action": "https://jobs.example.com/submit", "method": "post", "button_text": "Apply", "valid": "true", "fields": "[[\"name\",\"Ada\"]]"}
    page = FakePage(pending=pending)
    outcome, browser = run_with(page, FakeModel({"type": "click", "x": 10, "y": 20}))
    assert outcome.status == "pending_approval"
    assert outcome.submit_fingerprint == submit_fingerprint("app-1", pending)
    assert not page.approved
    assert "submit" in browser.context.script and "preventDefault" in browser.context.script


def test_approved_intercepted_submit_is_released_once():
    pending = {"action": "https://jobs.example.com/submit", "method": "post", "button_text": "Apply", "valid": "true", "fields": "[[\"name\",\"Ada\"]]"}
    approvals = []
    outcome, _ = run_with(
        FakePage(pending=pending), FakeModel({"type": "click", "x": 1, "y": 2}),
        approve_submit=lambda fp, details: approvals.append((fp, details)) or True,
    )
    assert outcome.status == "blocked"
    assert outcome.reason == "Submission was not confirmed by a successful response"
    assert len(approvals) == 1


def test_step_limit_is_actionable_and_uses_fresh_context():
    outcome, browser = run_with(FakePage(), FakeModel({"type": "wait", "ms": 9000}), max_steps=1)
    assert outcome.status == "blocked" and outcome.reason == "Step limit reached"
    assert browser.context_calls == 1
    assert browser.context_options == {"viewport": {"width": 1024, "height": 768}}
    assert browser.context.page.actions == [("wait", 5000)]
    assert browser.context.routes[0][0] == "**/*"


def test_model_safety_checks_require_explicit_acknowledgement_before_action():
    class SafetyModel(FakeModel):
        def __init__(self):
            super().__init__({
                "type": "click", "x": 1, "y": 2,
                "_safety_checks": ({"id": "sc-1", "code": "confirm", "message": "Confirm"},),
            })
            self.acknowledged = ()
        def acknowledge_safety_checks(self, checks): self.acknowledged = checks

    model = SafetyModel()
    outcome, browser = run_with(FakePage(), model)
    assert outcome.status == "pending_approval"
    assert not browser.context.page.actions and not model.acknowledged

    model = SafetyModel()
    outcome, browser = run_with(FakePage(), model, acknowledge_safety_checks=lambda checks: True)
    assert browser.context.page.actions[0] == ("click", 1, 2)
    assert model.acknowledged[0]["id"] == "sc-1"


class FakeRoute:
    def __init__(self): self.result = None
    def continue_(self): self.result = "continued"
    def abort(self, reason): self.result = ("aborted", reason)


class FakeRequest:
    def __init__(self, url, method="GET", post_data=None, resource_type="document"):
        self.url, self.method, self.post_data, self.resource_type = url, method, post_data, resource_type


def test_controlled_proxy_rejects_private_dns_and_non_connect_requests():
    proxy = _ControlledConnectProxy(
        lambda *a, **k: [(None, None, None, None, ("127.0.0.1", 443))]
    )
    proxy.start()
    try:
        host, port = proxy._server.server_address
        with socket.create_connection((host, port), timeout=2) as client:
            client.sendall(b"CONNECT split.example:443 HTTP/1.1\r\nHost: split.example\r\n\r\n")
            assert b"403 Forbidden" in client.recv(1024)
        with socket.create_connection((host, port), timeout=2) as client:
            client.sendall(b"GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n")
            assert b"405 Method Not Allowed" in client.recv(1024)
    finally:
        proxy.close()


def test_network_guard_blocks_private_destinations_and_unapproved_posts():
    private = _NetworkGuard("app", lambda *_: True, lambda *a, **k: [(None, None, None, None, ("169.254.169.254", 443))])
    route = FakeRoute()
    private.handle(route, FakeRequest("https://metadata.example/path"))
    assert route.result[0] == "aborted"
    assert "non-public" in private.blocked_reason

    public = lambda *a, **k: [(None, None, None, None, ("93.184.216.34", 443))]
    guarded = _NetworkGuard("app", lambda *_: False, public)
    route = FakeRoute()
    guarded.handle(route, FakeRequest("https://jobs.example.com/apply", "POST", "name=Ada"))
    assert route.result[0] == "aborted"
    assert guarded.submitted_fingerprint is None


def test_network_guard_only_confirms_armed_matching_request_after_success_response():
    guard = _NetworkGuard("app", lambda *_: pytest.fail("network must not request a second approval"),
                          lambda *a, **k: [(None, None, None, None, ("93.184.216.34", 443))])
    details = {"action": "https://jobs.example.com/apply", "method": "post", "fields": "[[\"name\", \"Ada\"]]"}
    guard.arm_submission(details, "approved-fingerprint")
    request = FakeRequest("https://jobs.example.com/apply", "POST", "name=Ada")
    route = FakeRoute()
    guard.handle(route, request)
    assert route.result == "continued"
    assert guard.submitted_fingerprint is None
    duplicate = FakeRoute()
    guard.handle(duplicate, request)
    assert duplicate.result[0] == "aborted"
    assert guard.blocked_reason is None  # duplicate is blocked without clobbering the in-flight result

    guard.observe_response(Object(request=request, status=500))
    assert guard.submitted_fingerprint is None
    assert "HTTP 500" in guard.blocked_reason

    guard.blocked_reason = None
    guard.observe_response(Object(request=request, status=204))
    assert guard.confirmed
    assert guard.submitted_fingerprint == "approved-fingerprint"


def test_cv_bytes_are_only_attached_through_the_file_chooser_after_consent():
    page = FakePage()
    outcome, _ = run_with(
        page, FakeModel({"type": "done"}), cv_file_bytes=b"exact-cv", cv_file_name="resume.pdf"
    )
    assert outcome.status == "completed_without_submit"
    attached = []
    page.events["filechooser"](Object(set_files=lambda value: attached.append(value)))
    assert attached[0]["name"] == "resume.pdf"
    assert attached[0]["buffer"] == b"exact-cv"


def test_submit_approval_snapshot_includes_exact_cv_identity():
    pending = {"action": "https://jobs.example.com/apply", "method": "post", "button_text": "Apply", "valid": "true", "fields": '[["cv","resume.pdf:8"]]'}
    reviewed = []
    outcome, _ = run_with(
        FakePage(pending=pending), FakeModel({"type": "click", "x": 1, "y": 2}),
        cv_file_bytes=b"exact-cv", cv_file_name="resume.pdf",
        approve_submit=lambda fp, details: reviewed.append(dict(details)) or True,
    )
    assert outcome.status == "blocked"  # fake page emits no network response
    assert reviewed[0]["cv_file_name"] == "resume.pdf"
    assert reviewed[0]["cv_file_size"] == "8"
    assert len(reviewed[0]["cv_sha256"]) == 64


def test_multipart_submission_matches_exact_cv_hash_and_text_fields():
    cv = b"exact pdf bytes"
    boundary = "tau-boundary"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"name\"\r\n\r\nAda\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"cv\"; filename=\"resume.pdf\"\r\n"
        "Content-Type: application/pdf\r\n\r\n"
    ).encode() + cv + f"\r\n--{boundary}--\r\n".encode()
    public = lambda *a, **k: [(None, None, None, None, ("93.184.216.34", 443))]
    guard = _NetworkGuard("app", lambda *_: True, public)
    details = {
        "action": "https://jobs.example.com/apply", "method": "post",
        "fields": '[["name","Ada"],["cv","resume.pdf:15"]]',
        "cv_file_name": "resume.pdf", "cv_file_size": str(len(cv)),
        "cv_sha256": __import__("hashlib").sha256(cv).hexdigest(),
    }
    guard.arm_submission(details, "approved")
    request = FakeRequest("https://jobs.example.com/apply", "POST", resource_type="document")
    request.header_value = lambda name: f"multipart/form-data; boundary={boundary}"
    request.post_data_buffer = body
    route = FakeRoute()
    guard.handle(route, request)
    assert route.result == "continued"

    tampered = body.replace(cv, b"tampered cv data")
    other = _NetworkGuard("app", lambda *_: True, public)
    other.arm_submission(details, "approved")
    request.post_data_buffer = tampered
    route = FakeRoute()
    other.handle(route, request)
    assert route.result[0] == "aborted"


def test_json_submission_requires_exact_armed_body_and_is_released_once():
    public = lambda *a, **k: [(None, None, None, None, ("93.184.216.34", 443))]
    details = {
        "action": "https://jobs.example.com/api/apply", "method": "post", "fields": "[]",
        "submit_kind": "json", "json_body": '{"answers":{"eligible":true},"name":"Ada"}',
    }
    guard = _NetworkGuard("app", lambda *_: True, public)
    guard.arm_submission(details, "json-approved")
    request = FakeRequest(
        "https://jobs.example.com/api/apply", "POST",
        '{"answers":{"eligible":true},"name":"Ada"}', "fetch",
    )
    request.header_value = lambda name: "application/json; charset=utf-8"
    route = FakeRoute()
    guard.handle(route, request)
    assert route.result == "continued"

    duplicate = FakeRoute()
    guard.handle(duplicate, request)
    assert duplicate.result[0] == "aborted"
    guard.blocked_reason = None
    guard.observe_response(Object(request=request, status=201))
    assert guard.confirmed and guard.submitted_fingerprint == "json-approved"


def test_json_submission_tamper_is_blocked():
    public = lambda *a, **k: [(None, None, None, None, ("93.184.216.34", 443))]
    guard = _NetworkGuard("app", lambda *_: True, public)
    guard.arm_submission({
        "action": "https://jobs.example.com/api/apply", "method": "post", "fields": "[]",
        "submit_kind": "json", "json_body": '{"name":"Ada"}',
    }, "approved")
    request = FakeRequest("https://jobs.example.com/api/apply", "POST", '{"name":"Mallory"}', "xhr")
    request.header_value = lambda name: "application/json"
    route = FakeRoute()
    guard.handle(route, request)
    assert route.result[0] == "aborted"
    assert "payload did not match" in guard.blocked_reason


def test_armed_json_and_multipart_payloads_fail_closed_when_not_body_bindable():
    public = lambda *a, **k: [(None, None, None, None, ("93.184.216.34", 443))]
    for content_type, body in (("application/json", '{"name":"Ada"}'), ("multipart/form-data; boundary=x", "--x")):
        guard = _NetworkGuard("app", lambda *_: True, public)
        guard.arm_submission(
            {"action": "https://jobs.example.com/apply", "method": "post", "fields": "[[\"name\",\"Ada\"]]"},
            "approved",
        )
        request = FakeRequest("https://jobs.example.com/apply", "POST", body, "xhr")
        request.header_value = lambda name, value=content_type: value
        route = FakeRoute()
        guard.handle(route, request)
        assert route.result[0] == "aborted"
        assert "payload did not match" in guard.blocked_reason
        assert guard.submitted_fingerprint is None


def test_json_approval_uses_semantics_not_language_specific_serialization():
    public = lambda *a, **k: [(None, None, None, None, ("93.184.216.34", 443))]
    guard = _NetworkGuard("app", lambda *_: True, public)
    guard.arm_submission({"action": "https://jobs.example.com/apply", "method": "post", "fields": "[]", "submit_kind": "json", "json_body": '{"name":"José","score":1e-7}'}, "approved")
    request = FakeRequest("https://jobs.example.com/apply", "POST", '{"name":"José","score":1e-7}', "xhr")
    request.header_value = lambda _name: "application/json"
    route = FakeRoute()
    guard.handle(route, request)
    assert route.result == "continued"


def test_submission_approval_binds_query_routing_parameters():
    public = lambda *a, **k: [(None, None, None, None, ("93.184.216.34", 443))]
    guard = _NetworkGuard("app", lambda *_: True, public)
    guard.arm_submission({"action": "https://jobs.example.com/apply?job=approved", "method": "post", "fields": "[]"}, "approved")
    route = FakeRoute()
    guard.handle(route, FakeRequest("https://jobs.example.com/apply?job=different", "POST", ""))
    assert route.result[0] == "aborted"
    assert "target did not match" in guard.blocked_reason


def test_ordinary_get_xhr_is_allowed_but_unarmed_post_is_blocked_without_approval():
    calls = []
    public = lambda *a, **k: [(None, None, None, None, ("93.184.216.34", 443))]
    guard = _NetworkGuard("app", lambda *args: calls.append(args) or True, public)
    get_route = FakeRoute()
    guard.handle(get_route, FakeRequest("https://jobs.example.com/options", resource_type="xhr"))
    assert get_route.result == "continued"
    post_route = FakeRoute()
    guard.handle(post_route, FakeRequest("https://jobs.example.com/save", "POST", "x=1", "xhr"))
    assert post_route.result[0] == "aborted"
    assert calls == []


class Object:
    def __init__(self, **values): self.__dict__.update(values)


class FakeResponses:
    def __init__(self, responses): self.responses = iter(responses); self.requests = []
    def create(self, **request): self.requests.append(request); return next(self.responses)


def test_openai_adapter_preserves_response_protocol_and_acknowledges_checks():
    safety_check = Object(model_dump=lambda: {"id": "safe-1", "code": "x", "message": "Review"})
    first_call = Object(
        type="computer_call", call_id="call-1",
        action=Object(model_dump=lambda: {"type": "click", "x": 3, "y": 4}),
        pending_safety_checks=[safety_check],
    )
    second_call = Object(
        type="computer_call", call_id="call-2",
        action=Object(model_dump=lambda: {"type": "keypress", "keys": "TAB"}),
        pending_safety_checks=[],
    )
    responses = FakeResponses([
        Object(id="response-1", output=[first_call]),
        Object(id="response-2", output=[second_call]),
    ])
    adapter = OpenAIResponsesComputerUse(client=Object(responses=responses))

    first = adapter.next_action(screenshot=b"first", instructions="private instructions")
    assert first["_safety_checks"][0]["id"] == "safe-1"
    assert "previous_response_id" not in responses.requests[0]
    assert responses.requests[0]["tools"][0]["display_width"] == 1024

    adapter.acknowledge_safety_checks(first["_safety_checks"])
    second = adapter.next_action(screenshot=b"second", instructions="not repeated")
    request = responses.requests[1]
    assert second["type"] == "keypress"
    assert request["previous_response_id"] == "response-1"
    assert request["input"][0]["type"] == "computer_call_output"
    assert request["input"][0]["call_id"] == "call-1"
    assert request["input"][0]["output"]["type"] == "computer_screenshot"
    assert request["input"][0]["acknowledged_safety_checks"][0]["id"] == "safe-1"
    assert "private instructions" not in str(request)


def test_openai_adapter_rejects_success_response_without_computer_call():
    adapter = OpenAIResponsesComputerUse(client=Object(responses=FakeResponses([Object(id="response-1", output=[Object(type="message")])])))
    with pytest.raises(ComputerUseError, match="returned no computer_call"):
        adapter.next_action(screenshot=b"image", instructions="apply")


def test_openai_adapter_reports_unsupported_computer_use_clearly():
    class UnsupportedResponses:
        def create(self, **request):
            raise RuntimeError("Unsupported tool: computer_use_preview is not supported")

    adapter = OpenAIResponsesComputerUse(client=Object(responses=UnsupportedResponses()), model="chat-only")
    with pytest.raises(ComputerUseError, match="chat-completions compatibility is not sufficient"):
        adapter.next_action(screenshot=b"image", instructions="apply")
