"""Safety-focused, local computer-use runner for job application pages.

Playwright and OpenAI are optional and imported only by their concrete adapters.  The
runner also accepts fakes, which keeps its safety policy independently testable.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import mimetypes
from email import policy
from email.parser import BytesParser
from pathlib import Path
import select
import socket
import socketserver
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import parse_qsl, urlsplit


class ComputerUseError(ValueError):
    """Raised for invalid configuration or model actions."""


@dataclass(frozen=True)
class RunOutcome:
    status: str
    reason: str
    steps: int = 0
    submit_fingerprint: str | None = None


ConsentCallback = Callable[[str], bool]
ApprovalCallback = Callable[[str, Mapping[str, str]], bool]
SafetyCheckCallback = Callable[[tuple[Mapping[str, str], ...]], bool]


class ModelAdapter(Protocol):
    def next_action(self, *, screenshot: bytes, instructions: str) -> Mapping[str, Any]: ...


_BLOCKED_MARKERS = (
    "captcha", "verify you are human", "access denied", "access restricted",
    "unusual traffic", "security check", "cloudflare challenge", "are you a robot",
    "automated requests", "automation detected", "bot detection",
)
_CONSENT_MARKERS = ("cookie consent", "privacy consent", "accept cookies", "consent required")
_SUPPORTED_ACTIONS = {
    "click", "double_click", "move", "drag", "scroll", "type", "keypress", "wait", "screenshot", "done"
}


def validate_public_https_url(url: str) -> str:
    """Validate a syntactically public HTTPS job URL without making a network request."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ComputerUseError("Invalid job URL") from exc
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ComputerUseError("Job URL must be an HTTPS public URL without credentials")
    if port not in (None, 443):
        raise ComputerUseError("Job URL must use the standard HTTPS port")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ComputerUseError("Local or internal job URLs are not allowed")
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        if "." not in host:
            raise ComputerUseError("Job URL must have a public hostname")
    else:
        if not address.is_global:
            raise ComputerUseError("Private, loopback, or reserved job URLs are not allowed")
    return url


def validate_action(action: Mapping[str, Any]) -> dict[str, Any]:
    """Return a normalized action or reject unsupported/malformed model output."""
    if not isinstance(action, Mapping):
        raise ComputerUseError("Model action must be an object")
    result = dict(action)
    kind = result.get("type")
    if kind not in _SUPPORTED_ACTIONS:
        raise ComputerUseError(f"Unsupported computer action: {kind!r}")

    def number(name: str) -> float:
        value = result.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ComputerUseError(f"Action {kind!r} requires numeric {name}")
        if abs(float(value)) > 100_000:
            raise ComputerUseError(f"Action coordinate {name} is out of bounds")
        return float(value)

    if kind in {"click", "double_click", "move"}:
        number("x"); number("y")
        if "button" in result and result["button"] not in {"left", "right", "wheel", "back", "forward"}:
            raise ComputerUseError("Invalid mouse button")
        if "keys" in result and not _valid_keys(result["keys"]):
            raise ComputerUseError("Invalid click keys")
    elif kind == "drag":
        path = result.get("path")
        if not isinstance(path, list) or len(path) < 2:
            raise ComputerUseError("Drag requires a path with at least two points")
        for point in path:
            if not isinstance(point, Mapping):
                raise ComputerUseError("Drag path points must be objects")
            for name in ("x", "y"):
                value = point.get(name)
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ComputerUseError(f"Drag point requires numeric {name}")
    elif kind == "scroll":
        for name in ("x", "y", "scroll_x", "scroll_y"):
            number(name)
    elif kind == "type":
        if not isinstance(result.get("text"), str) or not result["text"]:
            raise ComputerUseError("Action 'type' requires non-empty text")
    elif kind == "keypress" and not _valid_keys(result.get("keys")):
        raise ComputerUseError("Action 'keypress' requires a non-empty keys list")
    elif kind == "wait" and "ms" in result:
        number("ms")
    return result


def _valid_keys(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(key, str) and key for key in value)
    return result


def submit_fingerprint(application_id: str, details: Mapping[str, str]) -> str:
    canonical = json.dumps(
        {"application_id": application_id, **dict(sorted(details.items()))},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


_INTERCEPT_SCRIPT = r"""
(() => {
  const state = window.__tauSubmitGuard = { pending: null, allowOnce: false, jsIntent: false };
  const canonicalJSON = value => {
    if (Array.isArray(value)) return '[' + value.map(canonicalJSON).join(',') + ']';
    if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + canonicalJSON(value[k])).join(',') + '}';
    return JSON.stringify(value);
  };
  const describe = (button, form) => ({
    action: form ? (form.action || location.href) : location.href,
    method: form ? (form.method || 'get').toLowerCase() : '',
    button_text: (button && (button.innerText || button.value || button.name || button.id) || '').trim().slice(0, 200),
    page_url: location.href,
    valid: form ? String(form.checkValidity()) : 'false',
    fields: form ? JSON.stringify(Array.from(new FormData(form, button || undefined).entries()).map(([k, v]) => [k, typeof v === 'string' ? v : `${v.name}:${v.size}`])) : '[]'
  });
  const stop = (event, button, form) => {
    if (state.allowOnce) { state.allowOnce = false; return; }
    event.preventDefault(); event.stopImmediatePropagation();
    state.pending = { button, form, details: describe(button, form) };
  };
  document.addEventListener('submit', e => stop(e, e.submitter, e.target), true);
  document.addEventListener('click', e => {
    const b = e.target && e.target.closest && e.target.closest('button, input[type=submit], input[type=image]');
    if (!b) return;
    if (b.form && (b.type === 'submit' || b.tagName === 'INPUT')) stop(e, b, b.form);
    else {
      state.jsIntent = true;
      // Keep intent through the target's click handler. Microtasks can run
      // between capture and target listeners; a zero-delay task covers both.
      setTimeout(() => { state.jsIntent = false; }, 0);
    }
  }, true);
  const originalFetch = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    if (state.allowOnce) { state.allowOnce = false; return originalFetch(input, init); }
    const method = String(init.method || (input && input.method) || 'GET').toLowerCase();
    const headers = new Headers(init.headers || (input && input.headers) || {});
    const body = init.body;
    if (!state.jsIntent || !['post','put','patch','delete'].includes(method) ||
        !headers.get('content-type')?.toLowerCase().startsWith('application/json') || typeof body !== 'string') {
      return originalFetch(input, init);
    }
    let parsed;
    try { parsed = JSON.parse(body); } catch (_) { return Promise.reject(new Error('Blocked unverifiable JSON submission')); }
    if (state.pending) {
      state.pending.details.valid = 'false';
      return Promise.reject(new Error('Blocked ambiguous JSON submission'));
    }
    const canonicalBody = canonicalJSON(parsed);
    init = {...init, body: canonicalBody};
    const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url, location.href).href;
    let resolve, reject;
    const result = new Promise((ok, no) => { resolve = ok; reject = no; });
    state.pending = {
      details: { action: url, method, button_text: '', page_url: location.href, valid: 'true', fields: '[]', submit_kind: 'json', json_body: canonicalBody },
      release: () => originalFetch(input, init).then(resolve, reject)
    };
    return result;
  };
  state.take = () => state.pending && state.pending.details;
  state.approve = () => {
    const p = state.pending; if (!p) return false;
    state.pending = null;
    if (p.release) { p.release(); return true; }
    if (!p.form) return false;
    state.allowOnce = true; p.form.requestSubmit(p.button || undefined); return true;
  };
})();
"""


def _prepare_cv_upload(path: str | None, data: bytes | None, name: str) -> dict[str, Any] | None:
    if path is not None and data is not None:
        raise ComputerUseError("Provide either cv_file_path or cv_file_bytes, not both")
    if path is None and data is None:
        return None
    if path is not None:
        file_path = Path(path).expanduser().resolve(strict=True)
        if not file_path.is_file():
            raise ComputerUseError("CV upload path must be a regular file")
        content = file_path.read_bytes()
        file_name = file_path.name
        playwright_value: Any = str(file_path)
    else:
        if not isinstance(data, bytes) or not data:
            raise ComputerUseError("CV upload bytes must be non-empty")
        content = data
        file_name = Path(name).name
        if not file_name or file_name in {".", ".."}:
            raise ComputerUseError("CV upload filename is invalid")
        playwright_value = {
            "name": file_name,
            "mimeType": mimetypes.guess_type(file_name)[0] or "application/octet-stream",
            "buffer": content,
        }
    if len(content) > 10 * 1024 * 1024:
        raise ComputerUseError("CV upload exceeds the 10 MiB safety limit")
    return {
        "playwright": playwright_value,
        "identity": {
            "cv_file_name": file_name,
            "cv_file_size": str(len(content)),
            "cv_sha256": hashlib.sha256(content).hexdigest(),
        },
    }


class _ControlledConnectProxy:
    """CONNECT-only proxy that resolves and connects itself, preventing Chromium DNS bypass."""

    def __init__(self, resolver: Callable[..., Any]) -> None:
        self.resolver = resolver
        self.pinned: dict[str, frozenset[str]] = {}
        self._server: socketserver.ThreadingTCPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        if self._server is None:
            raise ComputerUseError("Controlled proxy is not running")
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def start(self) -> None:
        owner = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                line = self.rfile.readline(8192).decode("latin-1", "replace").strip()
                parts = line.split()
                while True:
                    header = self.rfile.readline(8192)
                    if header in {b"\r\n", b"\n", b""}:
                        break
                if len(parts) != 3 or parts[0].upper() != "CONNECT":
                    self.wfile.write(b"HTTP/1.1 405 Method Not Allowed\r\nConnection: close\r\n\r\n")
                    return
                try:
                    host, separator, port_text = parts[1].rpartition(":")
                    if not separator or int(port_text) != 443:
                        raise ComputerUseError("Proxy permits HTTPS port 443 only")
                    address = owner._validated_address(host.strip("[]"))
                    upstream = socket.create_connection((address, 443), timeout=10)
                except (OSError, ValueError, ComputerUseError):
                    self.wfile.write(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
                    return
                self.wfile.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                self.wfile.flush()
                try:
                    owner._tunnel(self.connection, upstream)
                finally:
                    upstream.close()

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._server = Server(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def _validated_address(self, host: str) -> str:
        validate_public_https_url(f"https://{host}/")
        try:
            answers = self.resolver(host, 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise ComputerUseError("Could not resolve proxy destination") from exc
        addresses = frozenset(item[4][0].split("%", 1)[0] for item in answers)
        if not addresses or any(not ipaddress.ip_address(value).is_global for value in addresses):
            raise ComputerUseError("Proxy destination is not public")
        previous = self.pinned.setdefault(host.lower(), addresses)
        if previous != addresses:
            raise ComputerUseError("Proxy destination DNS changed")
        return sorted(addresses)[0]

    @staticmethod
    def _tunnel(client: socket.socket, upstream: socket.socket) -> None:
        sockets = (client, upstream)
        while True:
            readable, _, _ = select.select(sockets, (), (), 30)
            if not readable:
                return
            for source in readable:
                data = source.recv(65536)
                if not data:
                    return
                (upstream if source is client else client).sendall(data)

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None


class _NetworkGuard:
    """Validate every request destination and gate state-changing requests."""

    def __init__(self, application_id: str, approve: ApprovalCallback, resolver: Callable[..., Any]) -> None:
        self.application_id = application_id
        self.approve = approve
        self.resolver = resolver
        self.pinned: dict[str, frozenset[str]] = {}
        self.blocked_reason: str | None = None
        self.submitted_fingerprint: str | None = None
        self.armed_details: Mapping[str, str] | None = None
        self.armed_fingerprint: str | None = None
        self.pending_request: Any | None = None
        self.confirmed = False

    def arm_submission(self, details: Mapping[str, str], fingerprint: str) -> None:
        self.armed_details = dict(details)
        self.armed_fingerprint = fingerprint

    def handle(self, route: Any, request: Any) -> None:
        try:
            self._validate_destination(request.url)
            method = request.method.upper()
            resource_type = getattr(request, "resource_type", "")
            is_state_changing = method not in {"GET", "HEAD", "OPTIONS"}
            if self.armed_details is None:
                if is_state_changing:
                    # Once an approved request is in flight, unrelated page
                    # activity is still blocked but must not overwrite its
                    # confirmation or turn it into a failed application.
                    if self.pending_request is None:
                        self.blocked_reason = "Unexpected state-changing request blocked before submission approval"
                    route.abort("blockedbyclient")
                else:
                    route.continue_()
                return
            is_candidate = is_state_changing or resource_type in {"document", "fetch", "xhr"}
            if not is_candidate:
                route.continue_()
                return
            expected = urlsplit(self.armed_details.get("action", ""))
            actual = urlsplit(request.url)
            same_target = (
                (expected.scheme, expected.netloc, expected.path) == (actual.scheme, actual.netloc, actual.path)
                and sorted(parse_qsl(expected.query, keep_blank_values=True)) == sorted(parse_qsl(actual.query, keep_blank_values=True))
            )
            same_method = self.armed_details.get("method", "").upper() == method
            if not same_target or not same_method:
                self.blocked_reason = "Submission network target did not match the approved form"
                route.abort("blockedbyclient")
                return
            if not self._matches_approved_fields(request, method):
                self.blocked_reason = "Submission payload did not match the approved form values"
                route.abort("blockedbyclient")
                return
            self._validate_destination(request.url)
            # Consume the one-time authorization before releasing the request.
            # Any identical retry or duplicate submission is blocked below as
            # an unexpected unarmed state-changing request.
            self.pending_request = request
            self.armed_details = None
            route.continue_()
        except Exception as exc:
            self.blocked_reason = str(exc) if isinstance(exc, ComputerUseError) else "Network request blocked by safety policy"
            route.abort("blockedbyclient")

    def observe_response(self, response: Any) -> None:
        if self.pending_request is not None and response.request is self.pending_request:
            if 200 <= response.status < 400:
                self.confirmed = True
                self.submitted_fingerprint = self.armed_fingerprint
            else:
                self.blocked_reason = f"Submission request failed with HTTP {response.status}"

    def observe_request_failed(self, request: Any) -> None:
        if self.pending_request is request:
            self.blocked_reason = "Submission request failed before receiving a response"

    def _matches_approved_fields(self, request: Any, method: str) -> bool:
        try:
            approved = json.loads(self.armed_details.get("fields", "[]")) if self.armed_details else []
        except (TypeError, ValueError):
            return False
        if method == "GET":
            actual = parse_qsl(urlsplit(request.url).query, keep_blank_values=True)
        else:
            header_value = getattr(request, "header_value", None)
            content_type = header_value("content-type") if callable(header_value) else "application/x-www-form-urlencoded"
            if not content_type:
                return False
            if content_type.lower().startswith("multipart/form-data"):
                return self._matches_multipart(request, content_type, approved)
            if content_type.lower().startswith("application/json"):
                if not self.armed_details or self.armed_details.get("submit_kind") != "json":
                    return False
                try:
                    # The intercepted fetch is rewritten to this exact approved
                    # canonical body. Compare raw bytes to preserve JSON types.
                    actual_json = request.post_data or ""
                except (TypeError, ValueError):
                    return False
                return actual_json == self.armed_details.get("json_body")
            if not content_type.lower().startswith("application/x-www-form-urlencoded"):
                return False
            actual = parse_qsl(request.post_data or "", keep_blank_values=True)
        return sorted(map(tuple, approved)) == sorted(actual)

    def _matches_multipart(self, request: Any, content_type: str, approved: list[Any]) -> bool:
        if not self.armed_details or not self.armed_details.get("cv_sha256"):
            return False
        raw_value = getattr(request, "post_data_buffer", None)
        raw = raw_value() if callable(raw_value) else raw_value
        if not isinstance(raw, bytes):
            return False
        try:
            message = BytesParser(policy=policy.default).parsebytes(
                f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("ascii") + raw
            )
        except Exception:
            return False
        actual: list[tuple[str, str]] = []
        files = 0
        for part in message.iter_parts():
            field_name = part.get_param("name", header="content-disposition")
            if not field_name:
                return False
            payload = part.get_payload(decode=True) or b""
            filename = part.get_filename()
            if filename is None:
                actual.append((field_name, payload.decode(part.get_content_charset() or "utf-8", "strict")))
                continue
            files += 1
            if (
                filename != self.armed_details.get("cv_file_name")
                or str(len(payload)) != self.armed_details.get("cv_file_size")
                or hashlib.sha256(payload).hexdigest() != self.armed_details.get("cv_sha256")
            ):
                return False
            actual.append((field_name, f"{filename}:{len(payload)}"))
        return files == 1 and sorted(map(tuple, approved)) == sorted(actual)

    def _validate_destination(self, url: str) -> None:
        validate_public_https_url(url)
        host = urlsplit(url).hostname
        assert host is not None
        try:
            answers = self.resolver(host, 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise ComputerUseError("Could not safely resolve request destination") from exc
        addresses = frozenset(item[4][0].split("%", 1)[0] for item in answers)
        if not addresses or any(not ipaddress.ip_address(value).is_global for value in addresses):
            raise ComputerUseError("Request destination resolved to a non-public address")
        previous = self.pinned.setdefault(host, addresses)
        if addresses != previous:
            raise ComputerUseError("Request destination DNS changed during the application")


class ComputerUseRunner:
    """Drive one fresh browser context under conservative application safety rules."""

    def __init__(self, model: ModelAdapter, *, max_steps: int = 30, timeout_seconds: float = 300) -> None:
        if max_steps < 1 or timeout_seconds <= 0:
            raise ComputerUseError("Step and time bounds must be positive")
        self.model = model
        self.max_steps = max_steps
        self.timeout_seconds = timeout_seconds

    def run(
        self, *, job_url: str, application_id: str, instructions: str, cv_text: str,
        consent: ConsentCallback, approve_submit: ApprovalCallback,
        acknowledge_safety_checks: SafetyCheckCallback | None = None,
        browser_factory: Callable[[], Any] | None = None,
        resolver: Callable[..., Any] = socket.getaddrinfo,
        cv_file_path: str | None = None,
        cv_file_bytes: bytes | None = None,
        cv_file_name: str = "cv.pdf",
        cancel_event: Any | None = None,
    ) -> RunOutcome:
        def cancelled() -> bool:
            return bool(cancel_event is not None and cancel_event.is_set())

        validate_public_https_url(job_url)
        if not application_id:
            raise ComputerUseError("application_id is required")
        if not consent("Send CV text and job-page screenshots to the configured model"):
            return RunOutcome("pending_consent", "Model data sharing was not approved")
        if cancelled():
            return RunOutcome("cancelled", "Cancelled by user")
        cv_upload = _prepare_cv_upload(cv_file_path, cv_file_bytes, cv_file_name)

        proxy: _ControlledConnectProxy | None = None
        if browser_factory is None:
            proxy = _ControlledConnectProxy(resolver)
            proxy.start()
            try:
                browser = _playwright_browser(proxy.url)
            except Exception:
                proxy.close()
                raise
        else:
            browser = browser_factory()
        context = None
        started = time.monotonic()
        try:
            context = browser.new_context(viewport={"width": 1024, "height": 768})  # fresh, non-persistent profile
            network = _NetworkGuard(application_id, approve_submit, resolver)
            context.route("**/*", network.handle)
            context.on("response", network.observe_response)
            context.on("requestfailed", network.observe_request_failed)
            context.add_init_script(_INTERCEPT_SCRIPT)
            page = context.new_page()
            if cv_upload is not None:
                page.on("filechooser", lambda chooser: chooser.set_files(cv_upload["playwright"]))
            try:
                page.goto(job_url, wait_until="domcontentloaded")
            except Exception:
                if network.blocked_reason:
                    return RunOutcome("blocked", network.blocked_reason)
                raise
            if network.blocked_reason:
                return RunOutcome("blocked", network.blocked_reason)
            prompt = f"{instructions}\nCV text (private; user consented):\n{cv_text}"
            for step in range(1, self.max_steps + 1):
                if cancelled():
                    return RunOutcome("cancelled", "Cancelled by user", step - 1)
                if time.monotonic() - started >= self.timeout_seconds:
                    return RunOutcome("blocked", "Time limit reached", step - 1)
                reason = _page_block_reason(page)
                if reason:
                    return RunOutcome("blocked", reason, step - 1)
                shot = page.screenshot(type="png")
                try:
                    proposed = dict(self.model.next_action(screenshot=shot, instructions=prompt))
                    checks = tuple(proposed.pop("_safety_checks", ()))
                    if checks:
                        if acknowledge_safety_checks is None or not acknowledge_safety_checks(checks):
                            return RunOutcome("cancelled" if cancelled() else "pending_approval", "Cancelled by user" if cancelled() else "Model safety checks require acknowledgement", step - 1)
                        acknowledge = getattr(self.model, "acknowledge_safety_checks", None)
                        if acknowledge is None:
                            return RunOutcome("blocked", "Model adapter cannot acknowledge safety checks", step - 1)
                        acknowledge(checks)
                    action = validate_action(proposed)
                except ComputerUseError as exc:
                    return RunOutcome("blocked", str(exc), step - 1)
                if action["type"] == "done":
                    return RunOutcome("completed_without_submit", "Model finished without submission", step)
                _perform_action(page, action)
                if cancelled():
                    return RunOutcome("cancelled", "Cancelled by user", step)
                if network.blocked_reason:
                    return RunOutcome("blocked", network.blocked_reason, step)
                if network.submitted_fingerprint:
                    return RunOutcome("submitted", "State-changing request explicitly approved", step, network.submitted_fingerprint)
                pending = page.evaluate("window.__tauSubmitGuard && window.__tauSubmitGuard.take()")
                if pending:
                    if pending.get("valid") != "true":
                        return RunOutcome("blocked", "Required fields failed browser validation", step)
                    dom_snapshot = dict(pending)
                    reviewed = dict(dom_snapshot)
                    if cv_upload is not None:
                        reviewed.update(cv_upload["identity"])
                    fp = submit_fingerprint(application_id, reviewed)
                    if not approve_submit(fp, reviewed):
                        return RunOutcome("cancelled" if cancelled() else "pending_approval", "Cancelled by user" if cancelled() else "Explicit submit approval required", step, fp)
                    current = page.evaluate("window.__tauSubmitGuard && window.__tauSubmitGuard.take()")
                    if current != dom_snapshot:
                        return RunOutcome("blocked", "Submission details changed after approval", step, fp)
                    network.arm_submission(reviewed, fp)
                    if not page.evaluate("window.__tauSubmitGuard.approve()"):
                        return RunOutcome("blocked", "Submission target changed before approval", step, fp)
                    for _ in range(50):
                        if network.blocked_reason or network.confirmed:
                            break
                        if cancelled():
                            return RunOutcome("submission_unknown", "Stop requested after submission release; verify with the employer before retrying", step, fp)
                        page.wait_for_timeout(100)
                    if network.confirmed and network.submitted_fingerprint:
                        return RunOutcome("submitted", "Approved submission received a successful response", step, network.submitted_fingerprint)
                    if network.blocked_reason:
                        return RunOutcome("blocked", network.blocked_reason, step, fp)
                    return RunOutcome("blocked", "Submission was not confirmed by a successful response", step, fp)
            return RunOutcome("blocked", "Step limit reached", self.max_steps)
        finally:
            if context is not None:
                context.close()
            browser.close()
            if proxy is not None:
                proxy.close()


def _page_block_reason(page: Any) -> str | None:
    text = str(page.locator("body").inner_text(timeout=2_000)).lower()
    if any(marker in text for marker in _BLOCKED_MARKERS):
        return "CAPTCHA or access restriction detected"
    if any(marker in text for marker in _CONSENT_MARKERS):
        return "Site consent decision requires the user"
    frames = getattr(page, "frames", ())
    frame_text = " ".join(str(frame.locator("body").inner_text(timeout=1_000)).lower() for frame in frames[1:])
    frame_urls = " ".join(str(getattr(frame, "url", "")).lower() for frame in frames[1:])
    risky_frame_hosts = ("recaptcha", "hcaptcha", "challenges.cloudflare", "arkoselabs", "onetrust", "cookiebot")
    if any(marker in frame_urls for marker in risky_frame_hosts):
        return "CAPTCHA or consent iframe requires the user"
    combined = text + " " + frame_text
    if any(marker in combined for marker in _BLOCKED_MARKERS):
        return "CAPTCHA or access restriction detected"
    if any(marker in combined for marker in _CONSENT_MARKERS):
        return "Site consent decision requires the user"
    return None


def _perform_action(page: Any, action: Mapping[str, Any]) -> None:
    kind = action["type"]
    if kind in {"click", "double_click"}:
        button = action.get("button", "left")
        if button == "back": page.go_back()
        elif button == "forward": page.go_forward()
        else: _mouse_click(page, action, double=(kind == "double_click"))
    elif kind == "move": page.mouse.move(action["x"], action["y"])
    elif kind == "drag":
        page.mouse.move(action["path"][0]["x"], action["path"][0]["y"]); page.mouse.down()
        for point in action["path"][1:]: page.mouse.move(point["x"], point["y"])
        page.mouse.up()
    elif kind == "scroll":
        page.mouse.move(action["x"], action["y"]); page.mouse.wheel(action["scroll_x"], action["scroll_y"])
    elif kind == "type": page.keyboard.type(action["text"])
    elif kind == "keypress":
        for key in action["keys"]: page.keyboard.press(key)
    elif kind == "wait": page.wait_for_timeout(min(int(action.get("ms", 1000)), 5_000))


def _mouse_click(page: Any, action: Mapping[str, Any], *, double: bool) -> None:
    modifiers = action.get("keys", [])
    for key in modifiers:
        page.keyboard.down(key)
    try:
        method = page.mouse.dblclick if double else page.mouse.click
        method(action["x"], action["y"], button="middle" if action.get("button") == "wheel" else action.get("button", "left"))
    finally:
        for key in reversed(modifiers):
            page.keyboard.up(key)


class OpenAIResponsesComputerUse:
    """Minimal OpenAI Responses adapter; importing this module does not require openai."""

    def __init__(self, client: Any | None = None, *, model: str = "computer-use-preview") -> None:
        if client is None:
            try:
                from openai import OpenAI  # type: ignore
            except ImportError as exc:
                raise ComputerUseError("Install the optional 'openai' package to use this adapter") from exc
            client = OpenAI()
        self.client, self.model = client, model
        self._response_id: str | None = None
        self._call_id: str | None = None
        self._acknowledged_checks: tuple[Mapping[str, str], ...] = ()

    def acknowledge_safety_checks(self, checks: tuple[Mapping[str, str], ...]) -> None:
        """Record checks explicitly approved by the runner's user callback."""
        self._acknowledged_checks = checks

    def next_action(self, *, screenshot: bytes, instructions: str) -> Mapping[str, Any]:
        import base64
        image_url = "data:image/png;base64," + base64.b64encode(screenshot).decode("ascii")
        tools = [{
            "type": "computer_use_preview", "display_width": 1024,
            "display_height": 768, "environment": "browser",
        }]
        request: dict[str, Any] = {"model": self.model, "tools": tools}
        had_computer_exchange = self._response_id is not None
        if self._response_id is None:
            request["input"] = [{"role": "user", "content": [
                {"type": "input_text", "text": instructions},
                {"type": "input_image", "image_url": image_url},
            ]}]
        else:
            output: dict[str, Any] = {
                "type": "computer_call_output", "call_id": self._call_id,
                "output": {"type": "computer_screenshot", "image_url": image_url},
            }
            if self._acknowledged_checks:
                output["acknowledged_safety_checks"] = [dict(check) for check in self._acknowledged_checks]
            request.update(previous_response_id=self._response_id, input=[output])
            self._acknowledged_checks = ()

        try:
            response = self.client.responses.create(**request)
        except Exception as exc:
            message = str(exc).lower()
            if any(marker in message for marker in ("computer_use", "computer use", "responses api", "unsupported tool", "not supported")):
                raise ComputerUseError(
                    f"Model {self.model!r} does not support Responses computer use on this provider; "
                    "chat-completions compatibility is not sufficient"
                ) from exc
            status = getattr(exc, "status_code", None)
            suffix = f" (HTTP {status})" if status else ""
            raise ComputerUseError(f"Computer-use provider request failed: {type(exc).__name__}{suffix}") from exc
        self._response_id = getattr(response, "id", None)
        for item in getattr(response, "output", ()):
            if getattr(item, "type", None) != "computer_call":
                continue
            self._call_id = getattr(item, "call_id", None)
            action = getattr(item, "action", None)
            if hasattr(action, "model_dump"):
                result = action.model_dump()
            elif isinstance(action, Mapping):
                result = dict(action)
            else:
                raise ComputerUseError("Computer call contained no valid action")
            checks = getattr(item, "pending_safety_checks", ()) or ()
            result["_safety_checks"] = tuple(
                check.model_dump() if hasattr(check, "model_dump") else dict(check) for check in checks
            )
            return result
        if had_computer_exchange:
            return {"type": "done"}
        raise ComputerUseError(
            f"Model {self.model!r} returned no computer_call; it does not support the required Responses computer-use protocol"
        )


def _playwright_browser(proxy_url: str) -> Any:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError as exc:
        raise ComputerUseError("Install the optional 'playwright' package and browser to run computer use") from exc
    manager = sync_playwright().start()
    browser = manager.chromium.launch(
        headless=False,
        proxy={"server": proxy_url},
        args=["--proxy-bypass-list=<-loopback>"],
    )

    class _ManagedBrowser:
        def new_context(self, **kwargs: Any) -> Any:
            return browser.new_context(**kwargs)

        def close(self) -> None:
            try:
                browser.close()
            finally:
                manager.stop()

    return _ManagedBrowser()
