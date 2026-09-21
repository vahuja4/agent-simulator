"""The Agent adapter for the journey_agent conversation service, and the only
place in the harness that knows its transport: JSON over HTTP on localhost,
standard library only. Contract: ``docs/plans/langgraph-harness.md`` sections
1–3. Nothing here imports the agent's code or inspects how it is built.

Two halves:

- ``JourneyServiceAdapter`` — the four lifecycle operations. It keeps its own
  record of every exchange the service acknowledged, per conversation, so a
  failed retrieval still leaves the messages it really observed.
- ``normalize_raw_trace`` — raw Trace → ``NormalizedTrace``. It copies and
  never infers, assigns no Verdict, and leaves the raw payload untouched.
"""

from __future__ import annotations

import copy
import http.client
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from ..journey.definition import FixtureState
from ..journey.normalized_trace import (
    MESSAGE_ROLES,
    ActionError,
    Evidence,
    NormalizedTrace,
    TraceAction,
    TraceMessage,
)
from .conversation import (
    AdapterError,
    AgentReply,
    ConversationAdapter,
    ConversationHandle,
    RetrievedTrace,
)

PLATFORM = "journey-service"
RAW_TRACE_VERSION = "1"
# One LangGraph turn makes several model calls at up to 30 s each, with a retry.
DEFAULT_REQUEST_TIMEOUT_S = 120.0

_RECORDED_STATUSES = ("succeeded", "failed")
_ABSENT = object()


class RawTraceError(ValueError):
    """The raw Trace cannot be read at all: nothing in it can be trusted."""


# ----------------------------------------------------- the adapter's record


@dataclass
class _ConversationRecord:
    """What the adapter itself sent and saw acknowledged. Messages carry the
    service's ids; their ``sequence`` is ``None`` because the service's
    ordering counter is only in the Trace."""

    tool_failures: tuple[str, ...]
    messages: list[TraceMessage] = field(default_factory=list)
    unacknowledged: list[str] = field(default_factory=list)  # sends that raised


# -------------------------------------------------------------- the adapter


class JourneyServiceAdapter(ConversationAdapter):
    def __init__(
        self, base_url: str, *, request_timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._request_timeout_s = request_timeout_s
        # Never route localhost through a proxy configured in the environment.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self._records: dict[str, _ConversationRecord] = {}

    @property
    def base_url(self) -> str:
        return self._base_url

    def start_conversation(
        self, *, fixture_state: FixtureState, tool_failures: tuple[str, ...] = ()
    ) -> ConversationHandle:
        body = self._request(
            "POST",
            "/conversations",
            {
                "fixture_state": fixture_state.to_payload(),
                "tool_failures": list(tool_failures),
            },
            expect=201,
        )
        handle = ConversationHandle(
            conversation_id=_string(body, "conversation_id", "start", 201),
            fixture_state_sha256=_string(body, "fixture_state_sha256", "start", 201),
            agent=_string(body, "agent", "start", 201),
        )
        if handle.fixture_state_sha256 != fixture_state.sha256:
            self._discard(handle)
            raise AdapterError(
                "protocol",
                f"the service hashed the Fixture state to {handle.fixture_state_sha256}, "
                f"the harness to {fixture_state.sha256}: they do not hold the same state",
                status=201,
            )
        self._records[handle.conversation_id] = _ConversationRecord(tuple(tool_failures))
        return handle

    def send_message(self, handle: ConversationHandle, text: str) -> AgentReply:
        record = self._records.get(handle.conversation_id)
        try:
            body = self._request(
                "POST", f"{_path(handle)}/messages", {"text": text}, expect=200
            )
            reply_body = body.get("reply")
            if not isinstance(reply_body, dict):
                raise AdapterError("protocol", "send: reply is not an object", status=200)
            reply = AgentReply(
                user_message_id=_string(body, "user_message_id", "send", 200),
                message_id=_string(reply_body, "message_id", "send reply", 200),
                text=_string(reply_body, "text", "send reply", 200),
            )
        except AdapterError:
            if record is not None:
                record.unacknowledged.append(text)
            raise
        if record is not None:
            record.messages.append(TraceMessage(reply.user_message_id, None, "user", text))
            record.messages.append(TraceMessage(reply.message_id, None, "agent", reply.text))
        return reply

    def retrieve_trace(self, handle: ConversationHandle) -> RetrievedTrace:
        record = self._records.get(handle.conversation_id)
        try:
            raw = self._request("POST", f"{_path(handle)}/trace", None, expect=200)
        except AdapterError as error:
            reason = f"retrieval failed: {error}"
            return RetrievedTrace(None, _from_record(handle, record, reason), reason)
        try:
            _require_same_conversation(raw, handle)
            normalized = normalize_raw_trace(raw, record)
        except RawTraceError as error:
            reason = f"the raw Trace cannot be used: {error}"
            return RetrievedTrace(raw, _from_record(handle, record, reason), reason)
        return RetrievedTrace(raw, normalized, None)

    def release(self, handle: ConversationHandle) -> None:
        self._records.pop(handle.conversation_id, None)
        self._request("DELETE", _path(handle), None, expect=204)

    def _discard(self, handle: ConversationHandle) -> None:
        """Release a conversation this adapter refuses to use; the refusal is
        the error worth reporting, not a failure to clean up after it."""
        try:
            self.release(handle)
        except AdapterError:
            pass

    def _request(self, method: str, path: str, body: Any, *, expect: int) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self._base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data is not None else {},
        )
        try:
            try:
                response = self._opener.open(request, timeout=self._request_timeout_s)
                status = response.status
            except urllib.error.HTTPError as error:
                response, status = error, error.code
            with response:
                content = response.read()
        except (OSError, http.client.HTTPException) as exc:
            raise AdapterError("transport", self._transport_detail(method, path, exc)) from exc

        if status == expect:
            return None if expect == 204 else _json_object(content, status)
        raise _error_response(content, status)

    def _transport_detail(self, method: str, path: str, exc: BaseException) -> str:
        where = f"{method} {self._base_url}{path}"
        if isinstance(exc, TimeoutError) or isinstance(
            getattr(exc, "reason", None), TimeoutError
        ):
            return f"{where}: no answer within {self._request_timeout_s:g} s"
        return f"{where}: {type(exc).__name__}: {exc}"


def _path(handle: ConversationHandle) -> str:
    return "/conversations/" + urllib.parse.quote(handle.conversation_id, safe="")


def _json_object(content: bytes, status: int) -> dict[str, Any]:
    try:
        body = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdapterError(
            "protocol", f"the response body is not valid JSON: {exc}", status=status
        ) from None
    if not isinstance(body, dict):
        raise AdapterError(
            "protocol", "the response body is not a JSON object", status=status
        )
    return body


def _error_response(content: bytes, status: int) -> AdapterError:
    """``{"error": {"code", "message"}}`` is the service's own error; any
    other answer breaks the contract."""
    try:
        error = _json_object(content, status).get("error")
    except AdapterError as malformed:
        return malformed
    if isinstance(error, dict) and isinstance(error.get("code"), str):
        return AdapterError(
            "service", str(error.get("message", "")), status=status, code=error["code"]
        )
    return AdapterError(
        "protocol",
        f"status {status} without the documented error shape",
        status=status,
    )


def _string(body: Mapping[str, Any], key: str, operation: str, status: int) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value:
        raise AdapterError(
            "protocol", f"{operation}: {key} is missing or not a string", status=status
        )
    return value


# ------------------------------------------------------- raw → normalized


class _Gaps:
    """Which evidence classes have gaps, and why."""

    def __init__(self) -> None:
        self._partial = {"messages": False, "actions": False}
        self.reasons: list[str] = []

    def _mark(self, reason: str, *classes: str) -> None:
        for name in classes:
            self._partial[name] = True
        self.reasons.append(reason)

    def messages(self, reason: str) -> None:
        self._mark(reason, "messages")

    def actions(self, reason: str) -> None:
        self._mark(reason, "actions")

    def both(self, reason: str) -> None:
        self._mark(reason, "messages", "actions")

    def evidence(self) -> Evidence:
        return Evidence(
            messages="partial" if self._partial["messages"] else "available",
            actions="partial" if self._partial["actions"] else "available",
            reasons=tuple(self.reasons),
        )


def normalize_raw_trace(
    raw: Any, record: _ConversationRecord | None = None
) -> NormalizedTrace:
    """Copy a raw Trace (design note section 3) into a ``NormalizedTrace``.

    A field that is absent or of the wrong type becomes ``None`` /
    ``result_available: false`` / ``status: unknown``, its evidence class
    becomes ``partial`` and a reason is recorded. Nothing is derived: not a
    status from a payload, not a reference from ordering, not
    ``result_available`` from a status — it means "the raw action carries the
    ``result`` key", so a failed action recorded with ``"result": null`` is
    complete evidence.

    With ``record``, raw messages that disagree with what the adapter itself
    observed make the messages class ``partial``.

    Raises ``RawTraceError`` when the payload cannot be read as a raw Trace.
    """
    if not isinstance(raw, dict):
        raise RawTraceError("the payload is not a JSON object")
    if raw.get("trace_version") != RAW_TRACE_VERSION:
        raise RawTraceError(
            f"trace_version must be {RAW_TRACE_VERSION!r}, got {raw.get('trace_version')!r}"
        )
    conversation_id = raw.get("conversation_id")
    if not isinstance(conversation_id, str) or not conversation_id:
        raise RawTraceError("conversation_id is missing")
    events = raw.get("events")
    if not isinstance(events, list):
        raise RawTraceError("events is missing or not a list")

    gaps = _Gaps()
    if raw.get("sealed") is not True:
        gaps.both("the raw Trace is not marked sealed, so it may not be complete")
    fixture_state_sha256 = _value(raw, "fixture_state_sha256", str, "header", gaps.both)
    tool_failures = raw.get("tool_failures")
    if not isinstance(tool_failures, list) or not all(
        isinstance(name, str) for name in tool_failures
    ):
        gaps.both("header: tool_failures is missing or not a list of tool names")
        tool_failures = []

    messages: list[TraceMessage] = []
    actions: list[TraceAction] = []
    for index, event in enumerate(events):
        where = f"events[{index}]"
        kind = event.get("type") if isinstance(event, dict) else None
        if kind == "message":
            message = _message(event, where, gaps)
            if message is not None:
                messages.append(message)
        elif kind == "action":
            actions.append(_action(event, where, gaps))
        else:
            gaps.both(f"{where}: type {kind!r} is neither message nor action; not carried")

    _check_identities(messages, actions, gaps)
    if record is not None:
        _check_against_record(messages, record, gaps)

    return NormalizedTrace(
        conversation_id=conversation_id,
        platform=PLATFORM,
        fixture_state_sha256=fixture_state_sha256,
        tool_failures=tuple(tool_failures),
        evidence=gaps.evidence(),
        messages=tuple(messages),
        actions=tuple(actions),
    )


def _value(
    event: Mapping[str, Any],
    key: str,
    kind: type,
    where: str,
    gap: Callable[[str], None],
) -> Any:
    """The field if it is a non-empty value of ``kind``; otherwise ``None``
    and a recorded gap."""
    value = event.get(key, _ABSENT)
    if isinstance(value, kind) and not isinstance(value, bool) and (value or kind is not str):
        return value
    gap(
        f"{where}: {key} is absent"
        if value is _ABSENT
        else f"{where}: {key} is {value!r}, not a usable {kind.__name__}"
    )
    return None


def _reference(
    event: Mapping[str, Any], key: str, where: str, gap: Callable[[str], None]
) -> str | None:
    """A message reference. ``null`` is a recorded fact (the agent raised
    before replying), not a gap; an absent key is a gap."""
    if event.get(key, _ABSENT) is None:
        return None
    return _value(event, key, str, where, gap)


def _message(event: Mapping[str, Any], where: str, gaps: _Gaps) -> TraceMessage | None:
    role = event.get("role")
    if role not in MESSAGE_ROLES:
        gaps.messages(f"{where}: role {role!r} is outside {MESSAGE_ROLES}; not carried")
        return None
    return TraceMessage(
        message_id=_value(event, "message_id", str, where, gaps.messages),
        sequence=_value(event, "seq", int, where, gaps.messages),
        role=role,
        text=_value(event, "text", str, where, gaps.messages),
    )


def _action(event: Mapping[str, Any], where: str, gaps: _Gaps) -> TraceAction:
    status = event.get("status")
    if status not in _RECORDED_STATUSES:
        gaps.actions(f"{where}: status {status!r} is outside {_RECORDED_STATUSES}")
        status = "unknown"
    result_available = "result" in event
    if not result_available:
        gaps.actions(f"{where}: result is absent")
    arguments = _value(event, "arguments", dict, where, gaps.actions)
    return TraceAction(
        action_id=_value(event, "action_id", str, where, gaps.actions),
        sequence=_value(event, "seq", int, where, gaps.actions),
        tool_name=_value(event, "tool_name", str, where, gaps.actions),
        arguments=copy.deepcopy(arguments),
        result=copy.deepcopy(event.get("result")),
        result_available=result_available,
        status=status,
        error=_action_error(event, where, gaps),
        caused_by_message_id=_reference(event, "caused_by_message_id", where, gaps.actions),
        reply_message_id=_reference(event, "reply_message_id", where, gaps.actions),
    )


def _action_error(event: Mapping[str, Any], where: str, gaps: _Gaps) -> ActionError | None:
    if event.get("error", _ABSENT) is None:
        return None
    error = _value(event, "error", dict, where, gaps.actions)
    if error is None:
        return None
    return ActionError(
        code=_value(error, "code", str, f"{where}.error", gaps.actions),
        message=_value(error, "message", str, f"{where}.error", gaps.actions),
    )


def _check_identities(
    messages: list[TraceMessage], actions: list[TraceAction], gaps: _Gaps
) -> None:
    """Ids identify and ``seq`` is one counter: a repeat means neither can be
    relied on."""
    if _has_repeat(m.message_id for m in messages):
        gaps.messages("two messages share a message_id")
    if _has_repeat(a.action_id for a in actions):
        gaps.actions("two actions share an action_id")
    if _has_repeat(item.sequence for item in (*messages, *actions)):
        gaps.both("two events share a seq, so the ordering is not explicit")


def _has_repeat(values: Any) -> bool:
    known = [value for value in values if value is not None]
    return len(set(known)) != len(known)


def _check_against_record(
    messages: list[TraceMessage], record: _ConversationRecord, gaps: _Gaps
) -> None:
    by_id = {m.message_id: m for m in messages if m.message_id is not None}
    for seen in record.messages:
        raw = by_id.get(seen.message_id)
        if raw is None:
            gaps.messages(
                f"the adapter observed {seen.role} message {seen.message_id!r}, "
                "which the raw Trace does not hold"
            )
        elif (raw.role, raw.text) != (seen.role, seen.text):
            gaps.messages(
                f"message {seen.message_id!r} in the raw Trace differs from what "
                "the adapter observed"
            )
    observed_ids = {m.message_id for m in record.messages}
    unacknowledged = list(record.unacknowledged)
    for message in messages:
        if message.message_id in observed_ids:
            continue
        if message.role == "user" and message.text in unacknowledged:
            # A send that raised after the service recorded the user message
            # (500 agent_error): the adapter sent exactly this text.
            unacknowledged.remove(message.text)
            continue
        gaps.messages(
            f"the raw Trace holds {message.role} message {message.message_id!r}, "
            "which the adapter never observed"
        )


def _require_same_conversation(raw: Mapping[str, Any], handle: ConversationHandle) -> None:
    for key, expected in (
        ("conversation_id", handle.conversation_id),
        ("fixture_state_sha256", handle.fixture_state_sha256),
    ):
        if key in raw and raw[key] != expected:
            raise RawTraceError(
                f"{key} is {raw[key]!r}, but this conversation's is {expected!r}"
            )


def _from_record(
    handle: ConversationHandle, record: _ConversationRecord | None, reason: str
) -> NormalizedTrace:
    """The normalized Trace when no usable raw Trace exists: only the messages
    the adapter itself observed, no actions, every gap stated."""
    reasons = [reason]
    messages = tuple(record.messages) if record is not None else ()
    if messages:
        reasons.append(
            "messages are the adapter's own record of acknowledged exchanges; "
            "their sequence is unknown because the service's ordering was not retrieved"
        )
    if record is not None and record.unacknowledged:
        reasons.append(
            f"{len(record.unacknowledged)} sent message(s) were never acknowledged "
            "and are not carried"
        )
    return NormalizedTrace(
        conversation_id=handle.conversation_id,
        platform=PLATFORM,
        fixture_state_sha256=handle.fixture_state_sha256,
        tool_failures=record.tool_failures if record is not None else (),
        evidence=Evidence(
            messages="partial" if messages else "unavailable",
            actions="unavailable",
            reasons=tuple(reasons),
        ),
        messages=messages,
        actions=(),
    )
