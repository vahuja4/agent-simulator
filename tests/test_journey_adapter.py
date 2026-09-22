"""The conversation lifecycle adapter and raw → normalized Trace conversion.

Offline: the journey service is a fake inside this process, speaking the
design note's section 3 over real HTTP on an ephemeral localhost port.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from agentsim.adapters.conversation import AdapterError, ConversationAdapter
from agentsim.adapters.journey_service import (
    DEFAULT_REQUEST_TIMEOUT_S,
    JourneyServiceAdapter,
    RawTraceError,
    normalize_raw_trace,
)
from agentsim.journey import checks
from agentsim.journey.definition import FixtureState, load_fixture_state
from journey_trace_builder import journey_scenario

REPO = Path(__file__).resolve().parent.parent
RAW_SAMPLES = Path(__file__).parent / "fixtures" / "journey_agent_raw_traces"
UPDATE_FAILED = {"code": "update_failed", "message": "the appointment system rejected the update"}


# ------------------------------------------------------- the fake service


def _error(status: int, code: str, message: str) -> tuple[int, dict[str, Any]]:
    return status, {"error": {"code": code, "message": message}}


class FakeJourneyService:
    """Section 3 in miniature. ``script`` holds, per send, the actions the
    "agent" records and its reply (or an exception message, for
    ``500 agent_error``). ``override[operation]`` replaces one operation's
    answer with ``(status, bytes)`` or a callable returning that."""

    def __init__(self) -> None:
        self.script: list[tuple[list[dict[str, Any]], str | Exception]] = []
        self.override: dict[str, Any] = {}
        self.requests: list[tuple[str, Any]] = []
        self.conversations: dict[str, dict[str, Any]] = {}

    def handle(self, operation: str, conversation_id: str | None, body: Any):
        self.requests.append((operation, body))
        if operation in self.override:
            answer = self.override[operation]
            return answer() if callable(answer) else answer
        return getattr(self, f"_{operation}")(conversation_id, body)

    def _start(self, _: None, body: Any):
        canonical = json.dumps(
            body["fixture_state"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        conversation_id = f"conv-{len(self.conversations) + 1}"
        trace = {
            "trace_version": "1",
            "conversation_id": conversation_id,
            "agent": "stub",
            "sealed": False,
            "fixture_state_sha256": hashlib.sha256(canonical).hexdigest(),
            "tool_failures": list(body.get("tool_failures", [])),
            "events": [],
        }
        self.conversations[conversation_id] = trace
        return 201, {k: trace[k] for k in ("conversation_id", "fixture_state_sha256", "agent")}

    def _send(self, conversation_id: str, body: Any):
        trace = self.conversations.get(conversation_id)
        if trace is None:
            return _error(404, "unknown_conversation", f"no conversation {conversation_id!r}")
        if trace["sealed"]:
            return _error(409, "conversation_closed", "the Trace was retrieved")
        if not isinstance(body.get("text"), str) or not body["text"].strip():
            return _error(400, "invalid_request", "text must be a non-empty string")
        events = trace["events"]
        messages = sum(e["type"] == "message" for e in events)
        user_id, reply_id = f"m{messages + 1}", f"m{messages + 2}"
        events.append({"seq": len(events) + 1, "type": "message", "message_id": user_id,
                       "role": "user", "text": body["text"]})
        actions, reply = self.script.pop(0) if self.script else ([], "ok")
        failed = isinstance(reply, Exception)
        for action in actions:
            number = sum(e["type"] == "action" for e in events) + 1
            events.append({"seq": len(events) + 1, "type": "action", "action_id": f"a{number}",
                           "status": "succeeded", "error": None, **action,
                           "caused_by_message_id": user_id,
                           "reply_message_id": None if failed else reply_id})
        if failed:
            return _error(500, "agent_error", f"{type(reply).__name__}: {reply}")
        events.append({"seq": len(events) + 1, "type": "message", "message_id": reply_id,
                       "role": "agent", "text": reply})
        return 200, {"user_message_id": user_id, "reply": {"message_id": reply_id, "text": reply}}

    def _retrieve(self, conversation_id: str, _: Any):
        trace = self.conversations.get(conversation_id)
        if trace is None:
            return _error(404, "unknown_conversation", f"no conversation {conversation_id!r}")
        trace["sealed"] = True
        return 200, copy.deepcopy(trace)

    def _release(self, conversation_id: str, _: Any):
        if self.conversations.pop(conversation_id, None) is None:
            return _error(404, "unknown_conversation", f"no conversation {conversation_id!r}")
        return 204, None


class _Handler(BaseHTTPRequestHandler):
    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length)) if length else None
        parts = [p for p in self.path.split("/") if p]
        operation = {
            ("POST", 1): "start", ("POST", 3): "send" if parts[-1] == "messages" else "retrieve",
            ("DELETE", 2): "release",
        }[(self.command, len(parts))]
        conversation_id = parts[1] if len(parts) > 1 else None
        status, payload = self.server.fake.handle(operation, conversation_id, body)
        data = (
            payload if isinstance(payload, bytes)
            else b"" if payload is None
            else json.dumps(payload).encode("utf-8")
        )
        try:
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            pass  # the client gave up waiting (the timeout test)

    do_POST = do_DELETE = _handle

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture
def service():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    server.fake = FakeJourneyService()
    server.fake.url = f"http://127.0.0.1:{server.server_address[1]}"
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    yield server.fake
    server.shutdown()
    server.server_close()


@pytest.fixture
def adapter(service) -> JourneyServiceAdapter:
    return JourneyServiceAdapter(service.url, request_timeout_s=5)


@pytest.fixture(scope="module")
def fixture_state() -> FixtureState:
    return load_fixture_state(REPO / "journeys/appointment_rescheduling/fixture_state.yaml")


LOOKUP = {"tool_name": "lookup_appointments", "arguments": {"confirmation_code": "HSD-4821"},
          "result": {"appointments": [{"appointment_id": "A-1001"}]}}
SLOTS = {"tool_name": "find_available_slots", "arguments": {"appointment_id": "A-1001"},
         "result": {"slots": [{"slot_id": "S-101"}, {"slot_id": "S-102"}]}}
UPDATE = {"tool_name": "update_appointment",
          "arguments": {"appointment_id": "A-1001", "slot_id": "S-101"},
          "result": {"appointment": {"appointment_id": "A-1001"}}}
FAILED_UPDATE = {**UPDATE, "status": "failed", "result": None, "error": UPDATE_FAILED}


def _reschedule(service, adapter, fixture_state, update=UPDATE, tool_failures=()):
    service.script = [([LOOKUP, SLOTS], "Open slots: S-101, S-102."),
                      ([], "Move A-1001 to S-101?"),
                      ([update], "Done." if update is UPDATE else "The update failed.")]
    handle = adapter.start_conversation(fixture_state=fixture_state, tool_failures=tool_failures)
    replies = [adapter.send_message(handle, t) for t in ("Code HSD-4821.", "S-101 please", "yes")]
    return handle, replies


def _raises(kind: str, status: int | None, code: str | None, call, *args, **kwargs) -> AdapterError:
    with pytest.raises(AdapterError) as caught:
        call(*args, **kwargs)
    error = caught.value
    assert (error.kind, error.status, error.code) == (kind, status, code), str(error)
    return error


# ------------------------------------------------- the four operations


def test_the_four_operations_happy_path(service, adapter, fixture_state):
    assert isinstance(adapter, ConversationAdapter)

    handle, replies = _reschedule(service, adapter, fixture_state)
    retrieved = adapter.retrieve_trace(handle)
    adapter.release(handle)

    assert handle.conversation_id == "conv-1"
    assert handle.agent == "stub"
    assert [(r.user_message_id, r.message_id, r.text) for r in replies] == [
        ("m1", "m2", "Open slots: S-101, S-102."),
        ("m3", "m4", "Move A-1001 to S-101?"),
        ("m5", "m6", "Done."),
    ]
    assert retrieved.error is None
    assert retrieved.raw["sealed"] is True
    assert retrieved.normalized.evidence.to_dict() == {
        "messages": "available", "actions": "available", "reasons": []}
    assert [op for op, _ in service.requests] == [
        "start", "send", "send", "send", "retrieve", "release"]
    assert service.conversations == {}


def test_start_sends_fixture_state_and_tool_failures_inline_and_verifies_the_hash(
    service, adapter, fixture_state
):
    handle = adapter.start_conversation(
        fixture_state=fixture_state, tool_failures=("update_appointment",)
    )

    _, body = service.requests[0]
    assert body == {"fixture_state": fixture_state.to_payload(),
                    "tool_failures": ["update_appointment"]}
    assert handle.fixture_state_sha256 == fixture_state.sha256


def test_a_fixture_hash_mismatch_is_a_protocol_error_and_the_conversation_is_released(
    service, adapter, fixture_state
):
    real_start = service._start

    def wrong_hash():
        status, body = real_start(None, service.requests[-1][1])
        return status, {**body, "fixture_state_sha256": "0" * 64}

    service.override["start"] = wrong_hash

    error = _raises("protocol", 201, None, adapter.start_conversation, fixture_state=fixture_state)

    assert "0" * 64 in error.detail and fixture_state.sha256 in error.detail
    assert [op for op, _ in service.requests] == ["start", "release"]
    assert service.conversations == {}


def test_the_request_timeout_is_a_parameter_defaulting_to_120_seconds(service):
    assert DEFAULT_REQUEST_TIMEOUT_S == 120.0
    assert JourneyServiceAdapter(service.url)._request_timeout_s == 120.0


# ------------------------------------------------------- error shapes


def test_400_invalid_request(service, adapter, fixture_state):
    handle = adapter.start_conversation(fixture_state=fixture_state)

    error = _raises("service", 400, "invalid_request", adapter.send_message, handle, "   ")

    assert not error.agent_fault
    assert "non-empty" in error.detail


def test_404_unknown_conversation_including_after_release(service, adapter, fixture_state):
    handle = adapter.start_conversation(fixture_state=fixture_state)
    adapter.release(handle)

    _raises("service", 404, "unknown_conversation", adapter.send_message, handle, "hello")
    _raises("service", 404, "unknown_conversation", adapter.release, handle)


def test_409_send_after_retrieve(service, adapter, fixture_state):
    handle = adapter.start_conversation(fixture_state=fixture_state)
    adapter.retrieve_trace(handle)

    _raises("service", 409, "conversation_closed", adapter.send_message, handle, "one more")


def test_500_agent_error_is_the_agents_fault(service, adapter, fixture_state):
    service.script = [([LOOKUP], RuntimeError("model unavailable"))]
    handle = adapter.start_conversation(fixture_state=fixture_state)

    error = _raises("service", 500, "agent_error", adapter.send_message, handle, "Code HSD-4821.")

    assert error.agent_fault
    assert "model unavailable" in error.detail
    assert error.to_dict() == {"kind": "service", "status": 500, "code": "agent_error",
                               "detail": error.detail, "agent_fault": True}


def test_a_refused_connection_is_infrastructure(fixture_state):
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        port = unused.getsockname()[1]
    adapter = JourneyServiceAdapter(f"http://127.0.0.1:{port}", request_timeout_s=5)

    error = _raises("transport", None, None, adapter.start_conversation, fixture_state=fixture_state)

    assert not error.agent_fault


def test_a_request_timeout_is_infrastructure(service, fixture_state):
    def slow():
        time.sleep(0.5)
        return 200, {}

    service.override["send"] = slow
    adapter = JourneyServiceAdapter(service.url, request_timeout_s=0.1)
    handle = adapter.start_conversation(fixture_state=fixture_state)

    error = _raises("transport", None, None, adapter.send_message, handle, "hello")

    assert "no answer within 0.1 s" in error.detail
    assert not error.agent_fault


@pytest.mark.parametrize(
    "answer, status",
    [
        ((200, b"{not json"), 200),
        ((200, b"[1, 2]"), 200),
        ((200, {"user_message_id": "m1"}), 200),
        ((200, {"user_message_id": "m1", "reply": {"message_id": "m2"}}), 200),
        ((500, b"<html>oops</html>"), 500),
        ((503, {"unexpected": "shape"}), 503),
        ((201, {"user_message_id": "m1", "reply": {"message_id": "m2", "text": "hi"}}), 201),
    ],
)
def test_an_answer_outside_the_contract_is_a_protocol_error(
    service, adapter, fixture_state, answer, status
):
    handle = adapter.start_conversation(fixture_state=fixture_state)
    service.override["send"] = answer

    _raises("protocol", status, None, adapter.send_message, handle, "hello")


def test_an_unknown_error_kind_is_refused():
    with pytest.raises(ValueError):
        AdapterError("agent", "not a kind")


# ------------------------------------------------ retrieval and its gaps


def test_failed_retrieval_returns_the_gap_with_the_messages_the_adapter_observed(
    service, adapter, fixture_state
):
    handle, _ = _reschedule(
        service, adapter, fixture_state, tool_failures=("update_appointment",)
    )
    service.override["retrieve"] = _error(500, "internal_error", "boom")

    retrieved = adapter.retrieve_trace(handle)

    assert retrieved.raw is None
    assert retrieved.error == "retrieval failed: service 500 internal_error: boom"
    trace = retrieved.normalized
    assert (trace.evidence.messages, trace.evidence.actions) == ("partial", "unavailable")
    assert trace.evidence.reasons[0] == retrieved.error
    assert "sequence is unknown" in trace.evidence.reasons[1]
    assert [(m.message_id, m.sequence, m.role, m.text) for m in trace.messages] == [
        ("m1", None, "user", "Code HSD-4821."),
        ("m2", None, "agent", "Open slots: S-101, S-102."),
        ("m3", None, "user", "S-101 please"),
        ("m4", None, "agent", "Move A-1001 to S-101?"),
        ("m5", None, "user", "yes"),
        ("m6", None, "agent", "Done."),
    ]
    assert trace.actions == ()
    assert trace.conversation_id == handle.conversation_id
    assert trace.fixture_state_sha256 == fixture_state.sha256
    assert trace.tool_failures == ("update_appointment",)
    for result in checks.run_assertions(checks.ASSERTIONS, trace, journey_scenario()):
        assert result.status == "unavailable"


@pytest.mark.parametrize("failure", ["refused", "timeout", "malformed"])
def test_retrieve_trace_never_raises_for_a_service_side_problem(
    service, fixture_state, failure
):
    adapter = JourneyServiceAdapter(service.url, request_timeout_s=0.2)
    handle = adapter.start_conversation(fixture_state=fixture_state)
    if failure == "refused":
        adapter._base_url = "http://127.0.0.1:1"
    elif failure == "timeout":
        service.override["retrieve"] = lambda: (time.sleep(0.6), (200, {}))[1]
    else:
        service.override["retrieve"] = (200, b"{not json")

    retrieved = adapter.retrieve_trace(handle)

    assert retrieved.raw is None
    assert retrieved.error.startswith("retrieval failed: ")
    trace = retrieved.normalized
    assert (trace.evidence.messages, trace.evidence.actions) == ("unavailable", "unavailable")
    assert (trace.messages, trace.actions) == ((), ())


def test_an_unacknowledged_send_is_stated_not_carried(service, adapter, fixture_state):
    service.script = [([], "Hello."), ([LOOKUP], RuntimeError("model unavailable"))]
    handle = adapter.start_conversation(fixture_state=fixture_state)
    adapter.send_message(handle, "Hi")
    with pytest.raises(AdapterError):
        adapter.send_message(handle, "Code HSD-4821.")
    service.override["retrieve"] = _error(500, "internal_error", "boom")

    trace = adapter.retrieve_trace(handle).normalized

    assert [m.message_id for m in trace.messages] == ["m1", "m2"]
    assert "1 sent message(s) were never acknowledged" in trace.evidence.reasons[-1]


@pytest.mark.parametrize(
    "change, fragment",
    [
        ({"trace_version": "2"}, "trace_version"),
        ({"events": None}, "events is missing"),
        ({"conversation_id": "someone-else"}, "conversation_id is 'someone-else'"),
        ({"fixture_state_sha256": "f" * 64}, "fixture_state_sha256"),
    ],
)
def test_an_unusable_raw_trace_is_kept_and_nothing_is_read_from_it(
    service, adapter, fixture_state, change, fragment
):
    handle, _ = _reschedule(service, adapter, fixture_state)
    payload = {**service._retrieve(handle.conversation_id, None)[1], **change}
    service.override["retrieve"] = (200, payload)

    retrieved = adapter.retrieve_trace(handle)

    assert retrieved.raw == payload
    assert retrieved.error.startswith("the raw Trace cannot be used: ")
    assert fragment in retrieved.error
    trace = retrieved.normalized
    assert (trace.evidence.messages, trace.evidence.actions) == ("partial", "unavailable")
    assert len(trace.messages) == 6 and trace.actions == ()


def test_agent_error_leaves_a_complete_trace_with_no_reply(service, adapter, fixture_state):
    """The user message and the action stay recorded; ``reply_message_id`` is
    a recorded ``null``, not a gap, and the adapter's unacknowledged send
    accounts for the user message it never got an id for."""
    service.script = [([LOOKUP], RuntimeError("model unavailable"))]
    handle = adapter.start_conversation(fixture_state=fixture_state)
    with pytest.raises(AdapterError):
        adapter.send_message(handle, "Code HSD-4821.")

    retrieved = adapter.retrieve_trace(handle)
    adapter.release(handle)

    trace = retrieved.normalized
    assert retrieved.error is None
    assert trace.evidence.complete, trace.evidence.reasons
    assert [(m.message_id, m.role) for m in trace.messages] == [("m1", "user")]
    (action,) = trace.actions
    assert (action.caused_by_message_id, action.reply_message_id) == ("m1", None)


def test_raw_messages_that_disagree_with_what_the_adapter_observed_are_partial(
    service, adapter, fixture_state
):
    handle, _ = _reschedule(service, adapter, fixture_state)
    payload = service._retrieve(handle.conversation_id, None)[1]
    payload["events"][3]["text"] = "Something the adapter never received."
    del payload["events"][8]
    payload["events"].append({"seq": 10, "type": "message", "message_id": "m7",
                              "role": "agent", "text": "An extra message."})
    service.override["retrieve"] = (200, payload)

    retrieved = adapter.retrieve_trace(handle)

    evidence = retrieved.normalized.evidence
    assert retrieved.raw == payload
    assert (evidence.messages, evidence.actions) == ("partial", "available")
    assert evidence.reasons == (
        "message 'm2' in the raw Trace differs from what the adapter observed",
        "the adapter observed agent message 'm6', which the raw Trace does not hold",
        "the raw Trace holds agent message 'm7', which the adapter never observed",
    )
    # The raw Trace is what is normalized; the adapter's record only flags it.
    assert retrieved.normalized.message("m2").text == "Something the adapter never received."


# ---------------------------------------------------------- normalization


def _raw(*events: dict[str, Any], **header: Any) -> dict[str, Any]:
    return {"trace_version": "1", "conversation_id": "conv-1", "agent": "stub", "sealed": True,
            "fixture_state_sha256": "a" * 64, "tool_failures": [], "events": list(events),
            **header}


def _message(seq: int, message_id: str, role: str, text: str = "text") -> dict[str, Any]:
    return {"seq": seq, "type": "message", "message_id": message_id, "role": role, "text": text}


def _action(seq: int, **overrides: Any) -> dict[str, Any]:
    return {"seq": seq, "type": "action", "action_id": "a1", "status": "succeeded",
            "error": None, "caused_by_message_id": "m1", "reply_message_id": "m2",
            **LOOKUP, **overrides}


def _without(event: dict[str, Any], key: str) -> dict[str, Any]:
    return {k: v for k, v in event.items() if k != key}


def test_identities_the_single_ordering_and_references_survive(
    service, adapter, fixture_state
):
    handle, _ = _reschedule(service, adapter, fixture_state, update=FAILED_UPDATE,
                            tool_failures=("update_appointment",))

    retrieved = adapter.retrieve_trace(handle)

    trace = retrieved.normalized
    assert trace.platform == "journey-service"
    assert trace.conversation_id == handle.conversation_id
    assert trace.fixture_state_sha256 == fixture_state.sha256
    assert trace.tool_failures == ("update_appointment",)
    assert [(m.sequence, m.message_id, m.role) for m in trace.messages] == [
        (1, "m1", "user"), (4, "m2", "agent"), (5, "m3", "user"),
        (6, "m4", "agent"), (7, "m5", "user"), (9, "m6", "agent")]
    assert [(a.sequence, a.action_id, a.tool_name, a.caused_by_message_id, a.reply_message_id)
            for a in trace.actions] == [
        (2, "a1", "lookup_appointments", "m1", "m2"),
        (3, "a2", "find_available_slots", "m1", "m2"),
        (8, "a3", "update_appointment", "m5", "m6")]
    assert trace.actions[1].arguments == SLOTS["arguments"]
    assert trace.actions[1].result == SLOTS["result"]


def test_a_failed_action_with_a_null_result_is_complete_evidence():
    """``result_available`` means "the raw action carries the ``result`` key":
    AGENT writes ``"result": null`` for a failed action."""
    raw = _raw(_message(1, "m1", "user"), _action(2, **FAILED_UPDATE), _message(3, "m2", "agent"))

    trace = normalize_raw_trace(raw)

    (action,) = trace.actions
    assert trace.evidence.complete
    assert (action.result_available, action.result, action.status) == (True, None, "failed")
    assert action.error.to_dict() == UPDATE_FAILED


def test_the_raw_payload_is_left_untouched_and_not_aliased():
    raw = _raw(_message(1, "m1", "user"), _action(2), _message(3, "m2", "agent"))
    before = copy.deepcopy(raw)

    trace = normalize_raw_trace(raw)
    trace.actions[0].arguments["confirmation_code"] = "changed"
    trace.actions[0].result["appointments"].clear()

    assert raw == before


@pytest.mark.parametrize(
    "key, field, fragment",
    [
        ("action_id", "action_id", "action_id is absent"),
        ("seq", "sequence", "seq is absent"),
        ("tool_name", "tool_name", "tool_name is absent"),
        ("arguments", "arguments", "arguments is absent"),
        ("error", "error", "error is absent"),
        ("caused_by_message_id", "caused_by_message_id", "caused_by_message_id is absent"),
        ("reply_message_id", "reply_message_id", "reply_message_id is absent"),
    ],
)
def test_a_missing_action_field_becomes_unavailable_never_a_guess(key, field, fragment):
    raw = _raw(_message(1, "m1", "user"), _without(_action(2), key), _message(3, "m2", "agent"))

    trace = normalize_raw_trace(raw)

    assert getattr(trace.actions[0], field) is None
    assert (trace.evidence.messages, trace.evidence.actions) == ("available", "partial")
    assert trace.evidence.reasons == (f"events[1]: {fragment}",)


def test_a_missing_status_is_unknown_not_derived_from_the_payload():
    raw = _raw(_message(1, "m1", "user"), _without(_action(2, **FAILED_UPDATE), "status"),
               _message(3, "m2", "agent"))

    trace = normalize_raw_trace(raw)

    assert trace.actions[0].status == "unknown"
    assert trace.evidence.actions == "partial"
    for result in checks.run_assertions(checks.ASSERTIONS, trace, journey_scenario()):
        assert result.status == "unavailable"


def test_a_missing_result_key_is_not_available():
    raw = _raw(_message(1, "m1", "user"), _without(_action(2), "result"),
               _message(3, "m2", "agent"))

    trace = normalize_raw_trace(raw)

    assert (trace.actions[0].result_available, trace.actions[0].result) == (False, None)
    assert trace.evidence.actions == "partial"
    assert trace.evidence.reasons == ("events[1]: result is absent",)


@pytest.mark.parametrize("key, field", [("message_id", "message_id"), ("seq", "sequence"),
                                        ("text", "text")])
def test_a_missing_message_field_becomes_unavailable(key, field):
    raw = _raw(_without(_message(1, "m1", "user"), key), _message(2, "m2", "agent"))

    trace = normalize_raw_trace(raw)

    assert getattr(trace.messages[0], field) is None
    assert (trace.evidence.messages, trace.evidence.actions) == ("partial", "available")


def test_wrong_types_are_gaps_not_coerced():
    raw = _raw(_message(True, "m1", "user"), _action("2", arguments="code=1", error="boom"),
               _message(3, "m2", "agent", text=""))

    trace = normalize_raw_trace(raw)

    assert trace.messages[0].sequence is None
    assert trace.messages[1].text is None
    action = trace.actions[0]
    assert (action.sequence, action.arguments, action.error) == (None, None, None)
    assert (trace.evidence.messages, trace.evidence.actions) == ("partial", "partial")


def test_events_that_cannot_be_carried_are_stated():
    raw = _raw(_message(1, "m1", "system"), {"seq": 2, "type": "thought"}, "not an event")

    trace = normalize_raw_trace(raw)

    assert (trace.messages, trace.actions) == ((), ())
    assert (trace.evidence.messages, trace.evidence.actions) == ("partial", "partial")
    assert len(trace.evidence.reasons) == 3


def test_repeated_ids_or_sequence_numbers_are_gaps():
    raw = _raw(_message(1, "m1", "user"), _action(1), _action(3), _message(4, "m1", "agent"))

    evidence = normalize_raw_trace(raw).evidence

    assert (evidence.messages, evidence.actions) == ("partial", "partial")
    assert evidence.reasons == (
        "two messages share a message_id",
        "two actions share an action_id",
        "two events share a seq, so the ordering is not explicit",
    )


@pytest.mark.parametrize(
    "header", [{"sealed": False}, {"fixture_state_sha256": None}, {"tool_failures": "update"}]
)
def test_an_incomplete_header_makes_both_classes_partial(header):
    trace = normalize_raw_trace(_raw(_message(1, "m1", "user"), **header))

    assert (trace.evidence.messages, trace.evidence.actions) == ("partial", "partial")
    assert len(trace.evidence.reasons) == 1


@pytest.mark.parametrize(
    "raw", [[], _raw(trace_version="2"), _raw(conversation_id=None), _raw(events={})]
)
def test_a_payload_that_is_not_a_raw_trace_is_refused(raw):
    with pytest.raises(RawTraceError):
        normalize_raw_trace(raw)


# -------------------------------------------------------- contract tests
# Raw Traces produced by AGENT's stub service (journey_agent ee72c7f) for the
# conversation its own tests pin — tests/test_service.py RESCHEDULE over
# tests/fixtures/fixture_state.json — with and without the controlled tool
# failure. If AGENT's raw Trace format drifts, re-capture and these must still
# hold.


@pytest.mark.parametrize(
    "sample, tool_failures, expected_outcome, update_status",
    [
        ("successful", (), checks.OUTCOME_RESCHEDULED, "succeeded"),
        ("tool_failure", ("update_appointment",), checks.OUTCOME_UPDATE_FAILED_REPORTED, "failed"),
    ],
)
def test_agent_raw_trace_samples_normalize_to_complete_checkable_evidence(
    sample, tool_failures, expected_outcome, update_status
):
    raw = json.loads((RAW_SAMPLES / f"{sample}.json").read_text(encoding="utf-8"))
    scenario = journey_scenario(appointment_id="A-1", target_slot_ids=("S-2",),
                                tool_failures=tool_failures, expected_outcome=expected_outcome)

    trace = normalize_raw_trace(raw)

    assert trace.evidence.to_dict() == {
        "messages": "available", "actions": "available", "reasons": []}
    assert trace.tool_failures == tool_failures
    assert len(trace.messages) + len(trace.actions) == len(raw["events"])
    update = trace.actions[-1]
    assert (update.tool_name, update.status, update.result_available) == (
        "update_appointment", update_status, True)
    assert (update.result is None) == (update_status == "failed")

    results = checks.run_assertions(checks.ASSERTIONS, trace, scenario)
    assert {r.id for r in results} == set(checks.ASSERTIONS)
    assert all(r.status in ("passed", "failed") for r in results), results
    assert [r.status for r in results] == ["passed"] * 4  # the stub follows the rules
    assert checks.expected_outcome_evidenced(trace, scenario).evidenced
    assert len(trace.to_trace().turns) == len(trace.messages)


def test_agent_raw_trace_samples_carry_exactly_the_keys_the_normalizer_reads():
    for sample in ("successful", "tool_failure"):
        raw = json.loads((RAW_SAMPLES / f"{sample}.json").read_text(encoding="utf-8"))
        assert set(raw) == {"trace_version", "conversation_id", "agent", "sealed",
                            "fixture_state_sha256", "tool_failures", "events"}
        for event in raw["events"]:
            expected = (
                {"seq", "type", "message_id", "role", "text"}
                if event["type"] == "message"
                else {"seq", "type", "action_id", "tool_name", "arguments", "status",
                      "result", "error", "caused_by_message_id", "reply_message_id"}
            )
            assert set(event) == expected


# ----------------------------------------------------- the import boundary


def test_nothing_in_the_harness_imports_langgraph_langchain_or_the_agent():
    """``agentsim`` and the composition roots alike: LangGraph lives only in
    AGENT, and the harness talks to it over HTTP (session 09 widened this
    from ``agentsim`` alone)."""
    forbidden = {"langgraph", "langchain", "langchain_core", "journey_agent"}
    offenders = []
    paths = [
        path
        for package in ("agentsim", "scenario_synthesis", "scripts")
        for path in (REPO / package).rglob("*.py")
    ]
    for path in sorted(paths):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            else:
                continue
            offenders += [
                f"{path.relative_to(REPO)}: {name}"
                for name in names
                if name.split(".")[0] in forbidden
            ]
    assert offenders == []


def test_the_adapter_uses_only_the_standard_library_and_the_harness():
    source = (REPO / "agentsim/adapters/journey_service.py").read_text(encoding="utf-8")
    tops = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            tops |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            tops.add((node.module or "").split(".")[0])
    assert tops <= {"__future__", "copy", "http", "json", "urllib", "dataclasses", "typing"}
