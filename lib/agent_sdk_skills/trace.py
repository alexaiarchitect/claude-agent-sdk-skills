"""One event model for two kinds of evidence.

Everything a grader or a triage report reads is a list of :class:`TraceEvent`.
Two loaders produce it:

:func:`load_trace`
    the runner's own `*.trace.jsonl` (schema ``agent-sdk-skills.trace/1``), one
    JSON object per line, written while the agent ran.
:func:`load_session`
    a Claude Code session file, `~/.claude/projects/<encoded cwd>/<id>.jsonl`.
    That is evidence of a *real* run nobody instrumented, which is exactly what
    `agent-debug` needs when a user says "it did the wrong thing yesterday".

Both are tolerant by design. A trace from a newer runner may carry event types
this plugin has never heard of; a session file certainly will. **Unknown types
become `system` events, never dropped** — in the measured session, 5 of the 7
line types were undocumented bookkeeping (`ai-title`, `queue-operation`,
`atis-latch`, `last-prompt`, `attachment`), so a loader that dropped what it did
not recognize would discard most of the file and then report confidently on the
remainder.

Three things about session files are measured, not assumed, and each one breaks
the obvious implementation:

* **The `parentUuid` chain runs through `attachment` lines.** The assistant line
  pointed at an attachment's uuid, not at the user line. A loader that assumed
  user→assistant adjacency mis-orders any real session, so :func:`load_session`
  walks the whole uuid graph.
* **There is no result line, but there may be a `cost-state` line.** A session
  carries no `ResultMessage`, so no `num_turns` and no `terminal_reason`. An
  SDK-produced session (`entrypoint: "sdk-py"`) does write one `cost-state` line
  with the session totals, and :func:`load_session` reads it into a synthesised
  `result` event marked `imported_cost: true` (CONTRACTS section 13.2). So a
  `budget` grader can be decided on such a session while `terminal` and
  `structured_output` stay `NOT_EVALUATED` — never FAILED. A `claude -p` session
  has no `cost-state` line, and then there is no result event at all.
* **`version` is the CLI version, not the SDK's** (measured `"2.1.274"`). It
  lands on `init.cli_version`; `sdk_version` is a separate field the runner fills
  from `claude_agent_sdk.__version__`.

One gap is carried openly: the session-side tool-result key (`toolUseResult`) was
**not measured** — the measured session had no tool call. The loader reads it if
present and the fixtures do not claim its shape. The SDK-side analogue *is*
measured: `UserMessage.tool_use_result` for `Read` was
`{"type": "text", "file": {...}}`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from . import SYNTHETIC_TOOLS
from .graders import normalize_tool_name

SCHEMA = "agent-sdk-skills.trace/1"

#: Event types the schema defines. Anything else becomes `system`.
EVENT_TYPES = (
    "init", "user", "assistant_text", "thinking", "tool_use", "tool_result",
    "server_tool_use", "server_tool_result", "hook", "subagent", "rate_limit",
    "conversation_reset", "system", "result",
)

#: Session-JSONL line types that map onto message events; everything else is
#: bookkeeping and is kept as `system`.
SESSION_MESSAGE_TYPES = ("user", "assistant")

#: How much of a tool result the trace keeps inline.
CONTENT_TRUNCATION = 2048

_SRC_TRACE = "this plugin's trace schema (CONTRACTS §5)"


@dataclass
class TraceEvent:
    """One normalized event. `data` holds whatever the type-specific fields are.

    The envelope fields are promoted to attributes because every consumer reads
    them; the rest stays in `data` so a newer runner's extra fields survive a
    round trip instead of being silently dropped.
    """

    type: str
    i: int = 0
    t: str | None = None
    run_id: str | None = None
    case: str | None = None
    session_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    # -- convenience readers, so callers never re-spell the key names ----
    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    @property
    def tool(self) -> str | None:
        value = self.data.get("tool")
        return value if isinstance(value, str) else None

    @property
    def text(self) -> str:
        value = self.data.get("text")
        return value if isinstance(value, str) else ""

    @property
    def input(self) -> dict[str, Any]:
        value = self.data.get("input")
        return value if isinstance(value, dict) else {}

    @property
    def synthetic(self) -> bool:
        """A tool call the CLI fabricated rather than the model requesting it.

        Recomputed from the tool name when the flag is absent, so a trace written
        by an older runner still classifies `StructuredOutput` correctly.
        """
        flag = self.data.get("synthetic")
        if isinstance(flag, bool):
            return flag
        return (self.tool or "") in SYNTHETIC_TOOLS

    @property
    def is_error(self) -> bool:
        """`ToolResultBlock.is_error` is `null` on success, not `False`."""
        return bool(self.data.get("is_error"))

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"i": self.i, "type": self.type}
        if self.t is not None:
            out["t"] = self.t
        for key, value in (("run_id", self.run_id), ("case", self.case),
                           ("session_id", self.session_id)):
            if value is not None:
                out[key] = value
        out.update(self.data)
        return out


# ---------------------------------------------------------------------------
# the runner's own trace files
# ---------------------------------------------------------------------------

def parse_event(raw: dict[str, Any], *, index: int) -> TraceEvent:
    """One line of a trace file into an event.

    An unknown `type` is preserved: the event becomes `system` with the original
    name in `data["subtype"]`, so a triage report can still say what it saw.
    """
    payload = dict(raw)
    payload.pop("schema", None)
    event_type = str(payload.pop("type", "") or "system")
    i = payload.pop("i", index)
    event = TraceEvent(
        type=event_type if event_type in EVENT_TYPES else "system",
        i=int(i) if isinstance(i, int) else index,
        t=payload.pop("t", None),
        run_id=payload.pop("run_id", None),
        case=payload.pop("case", None),
        session_id=payload.pop("session_id", None),
        data=payload,
    )
    if event.type == "system" and event_type not in EVENT_TYPES:
        event.data.setdefault("subtype", event_type)
        event.data.setdefault("unknown_type", event_type)
    return event


def load_trace(path: Path | str) -> list[TraceEvent]:
    """Read a `*.trace.jsonl`. Malformed lines become `system` events.

    A truncated trace is the normal outcome of a killed run, and it is still the
    most useful artifact in the failure: the events before the cut are exactly
    what happened. So a JSON error on one line never loses the rest.
    """
    events: list[TraceEvent] = []
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as exc:
        return [TraceEvent(type="system", i=0, data={
            "subtype": "load_error", "error": str(exc), "path": str(file)})]
    for index, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            events.append(TraceEvent(type="system", i=index, data={
                "subtype": "parse_error", "error": str(exc), "line": index + 1,
                "raw": line[:200]}))
            continue
        if not isinstance(raw, dict):
            events.append(TraceEvent(type="system", i=index, data={
                "subtype": "parse_error", "error": "line is not an object", "line": index + 1}))
            continue
        events.append(parse_event(raw, index=index))
    return events


def iter_traces(directory: Path | str) -> Iterator[tuple[str, list[TraceEvent]]]:
    """Every `*.trace.jsonl` in a directory, filename first."""
    root = Path(directory)
    if not root.is_dir():
        return
    for file in sorted(root.glob("*.trace.jsonl")):
        yield file.name, load_trace(file)


def write_trace(path: Path | str, events: Sequence[TraceEvent]) -> None:
    """Write events back out, stamping the schema on line 0.

    Used by `import_session.py`: an imported session becomes a trace file so
    every free grader can run against it unchanged.
    """
    lines: list[str] = []
    for position, event in enumerate(events):
        payload = event.to_dict()
        if position == 0:
            payload = {"schema": SCHEMA, **payload}
        lines.append(json.dumps(payload, ensure_ascii=False))
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Claude Code session files
# ---------------------------------------------------------------------------

#: Sanitized project keys longer than this are truncated and get a hash suffix.
MAX_SANITIZED_LENGTH = 200


def _simple_hash(text: str) -> str:
    """The CLI's 32-bit string hash, in base36.

    A djb2-style rolling hash (`h * 31 + char`) truncated to a signed 32-bit int
    the way JavaScript's `h |= 0` does, then `Math.abs(...).toString(36)`. It is
    reimplemented rather than replaced by Python's `hash()` because the value
    ends up in a directory name the CLI also computes: any other hash looks in
    the wrong place for long paths.
    """
    h = 0
    for char in text:
        h = (h << 5) - h + ord(char)
        h &= 0xFFFFFFFF
        if h >= 0x80000000:
            h -= 0x100000000
    h = abs(h)
    if h == 0:
        return "0"
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out: list[str] = []
    while h > 0:
        out.append(digits[h % 36])
        h //= 36
    return "".join(reversed(out))


def project_key_for_directory(cwd: str | Path | None = None, *, canonicalize: bool = True) -> str:
    """The `~/.claude/projects/` directory name for a working directory.

    The SDK ships `project_key_for_directory()`; this is the stdlib
    reimplementation, because `lib/` may never import the SDK. Three steps, and
    each one matters:

    1. **canonicalize** — `os.path.realpath` then Unicode NFC. macOS stores
       decomposed filenames, so a path with an accent resolves to a different key
       without the normalization.
    2. **sanitize** — every character outside `[a-zA-Z0-9]` becomes `-`. Not just
       the separators: dots and underscores are replaced too, so
       `/tmp/my_app.v2` becomes `-tmp-my-app-v2`.
    3. **truncate** — above 200 characters the key is cut to 200 and a base36
       hash of the *full* path is appended, so two long sibling paths do not
       collide.

    `canonicalize=False` skips step 1, for hashing a recorded `cwd` from a trace
    that was produced on another machine (where realpath would resolve against
    the wrong filesystem).

    `tests/lib/test_trace.py` compares this against the SDK's own answer when a
    virtualenv with the SDK is available, and skips otherwise: a reimplemented
    encoding that nobody checks is a silent way to read the wrong directory.
    """
    import re
    import unicodedata

    raw = str(cwd) if cwd is not None else "."
    if canonicalize:
        try:
            raw = os.path.realpath(raw)
        except OSError:
            pass
    name = unicodedata.normalize("NFC", raw)
    sanitized = re.sub(r"[^a-zA-Z0-9]", "-", name)
    if len(sanitized) <= MAX_SANITIZED_LENGTH:
        return sanitized
    return f"{sanitized[:MAX_SANITIZED_LENGTH]}-{_simple_hash(name)}"


def session_dir_for(cwd: str, *, home: Path | str | None = None) -> Path:
    """Where Claude Code keeps the sessions for one working directory."""
    root = Path(home) if home is not None else Path.home()
    return root / ".claude" / "projects" / project_key_for_directory(cwd)


def load_session(path: Path | str) -> list[TraceEvent]:
    """Read a Claude Code session JSONL into the same event model.

    The ordering problem is the whole difficulty. Lines arrive in write order,
    which is *mostly* chronological, but the conversation itself is a tree linked
    by `uuid`/`parentUuid`, and the chain runs **through attachment lines** — the
    measured assistant line's parent was an attachment, not the user turn. So:

    1. index every line that has a `uuid`;
    2. find the roots (`parentUuid` null or pointing outside the file) and walk
       children depth-first, so a line always follows its parent;
    3. keep lines with no `uuid` (`ai-title`, `queue-operation`, `atis-latch`,
       `last-prompt`) in file order, interleaved at the position they appeared.

    Hook inputs are not parsed field by field, so the fields SDK 0.2.166 added
    (`prompt_id`, `effort`, `duration_ms`, `last_assistant_message`,
    `background_tasks`, `session_crons`) pass through bookkeeping lines and
    `hook` events untouched; nothing here requires or rejects them.

    `init` is synthesized from the first line that carries `version`/`cwd`,
    because a session file has no init line of its own but every consumer needs
    to know which CLI produced it and where it ran.
    """
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as exc:
        return [TraceEvent(type="system", i=0, data={
            "subtype": "load_error", "error": str(exc), "path": str(file)})]

    lines: list[dict[str, Any]] = []
    for index, raw_line in enumerate(text.splitlines()):
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            raw = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            lines.append({"type": "_parse_error", "error": str(exc), "line": index + 1})
            continue
        lines.append(raw if isinstance(raw, dict) else {"type": "_parse_error",
                                                        "error": "line is not an object",
                                                        "line": index + 1})

    ordered = _order_session_lines(lines)
    events: list[TraceEvent] = []
    counter = 0

    init = _session_init(lines, path=str(file))
    if init is not None:
        init.i = counter
        events.append(init)
        counter += 1

    turn = 0
    for raw in ordered:
        line_type = str(raw.get("type") or "system")
        session_id = raw.get("sessionId")
        stamp = raw.get("timestamp")
        if line_type == "user":
            turn += 1
            for event in _blocks_to_events(raw, role="user", turn=turn):
                event.i, event.t, event.session_id = counter, stamp, session_id
                events.append(event)
                counter += 1
            continue
        if line_type == "assistant":
            for event in _blocks_to_events(raw, role="assistant", turn=turn):
                event.i, event.t, event.session_id = counter, stamp, session_id
                events.append(event)
                counter += 1
            continue
        if line_type == "cost-state":
            events.append(_imported_result(raw, i=counter, t=stamp, session_id=session_id))
            counter += 1
            continue
        # Everything else is bookkeeping: kept, never dropped. `system` lines
        # (`stop_hook_summary` and friends) land here too, as `system` events.
        events.append(TraceEvent(
            type="system", i=counter, t=stamp, session_id=session_id,
            data={"subtype": line_type, "data": _summarize_bookkeeping(raw)},
        ))
        counter += 1
    return events


def _imported_result(raw: dict[str, Any], *, i: int, t: str | None,
                     session_id: str | None) -> TraceEvent:
    """A `result` event synthesised from a session's `cost-state` line.

    An SDK-produced session (`entrypoint: "sdk-py"`) writes one `cost-state`
    line holding the session's own totals, which is the only place an imported
    session reports what it spent. Reading it closes CONTRACTS section 12.9: a
    `budget` grader can now be decided on imported evidence.

    What it is *not* is a `ResultMessage`. There is no `subtype`, no
    `terminal_reason` and no `num_turns` in the line, so those stay `None`
    rather than being guessed, and `imported_cost: true` marks the event so a
    reader — and the `terminal` grader — can tell a cost the SDK reported from
    one the runner measured in process. `claude -p` sessions carry no
    `cost-state` line at all, so section 5.3's "no cost on import" still holds
    for them.

    `modelUsage` here is the camelCase per-model mapping the CLI writes, with
    the same undeclared `costBasis`/`thinkingTokens` keys the live
    `ResultMessage` carries, so it is read with `.get()` and never indexed.
    """
    model_usage = raw.get("modelUsage")
    if not isinstance(model_usage, dict):
        model_usage = {}
    model_usage = {str(k): dict(v) for k, v in model_usage.items() if isinstance(v, dict)}
    return TraceEvent(
        type="result", i=i, t=t, session_id=session_id,
        data={
            "subtype": None,
            "is_error": False,
            "terminal_reason": None,
            "stop_reason": None,
            "num_turns": None,
            "duration_ms": _int_or_none(raw.get("totalDuration")),
            "duration_api_ms": _int_or_none(raw.get("totalAPIDuration")),
            "total_cost_usd": _float_or_none(raw.get("totalCostUSD")),
            "cost_delta_usd": None,
            "usage": {},
            "model_usage": model_usage,
            "models_billed": sorted(model_usage),
            "cost_basis_list": all(
                entry.get("costBasis", "list") == "list" for entry in model_usage.values()
            ),
            "structured_output": None,
            "result_text": None,
            "permission_denials": [],
            "api_error_status": None,
            "imported_cost": True,
            "has_unknown_model_cost": bool(raw.get("hasUnknownModelCost")),
        },
    )


def _int_or_none(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _float_or_none(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _order_session_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """File order, corrected so every uuid-bearing line follows its parent."""
    by_uuid: dict[str, dict[str, Any]] = {}
    for raw in lines:
        uuid = raw.get("uuid")
        if isinstance(uuid, str):
            by_uuid.setdefault(uuid, raw)
    children: dict[str | None, list[dict[str, Any]]] = {}
    for raw in lines:
        if not isinstance(raw.get("uuid"), str):
            continue
        parent = raw.get("parentUuid")
        key = parent if isinstance(parent, str) and parent in by_uuid else None
        children.setdefault(key, []).append(raw)

    ordered: list[dict[str, Any]] = []
    emitted: set[int] = set()

    def walk(key: str | None) -> None:
        for child in children.get(key, []):
            marker = id(child)
            if marker in emitted:
                continue                  # a cycle, or a uuid reused
            emitted.add(marker)
            ordered.append(child)
            uuid = child.get("uuid")
            if isinstance(uuid, str):
                walk(uuid)

    walk(None)

    # Re-interleave the lines with no uuid at their original positions, and
    # append any uuid-bearing line the walk could not reach (a parent outside
    # this file, which happens for a resumed session).
    result: list[dict[str, Any]] = []
    walked = {id(raw) for raw in ordered}
    pending = list(ordered)
    for raw in lines:
        if isinstance(raw.get("uuid"), str) and id(raw) in walked:
            if pending:
                result.append(pending.pop(0))
            continue
        result.append(raw)
    result.extend(pending)
    for raw in lines:
        if isinstance(raw.get("uuid"), str) and id(raw) not in walked:
            result.append(raw)
    return result


def _session_init(lines: list[dict[str, Any]], *, path: str) -> TraceEvent | None:
    """Synthesize the `init` event a session file does not carry."""
    for raw in lines:
        if raw.get("version") or raw.get("cwd"):
            data: dict[str, Any] = {
                "cli_version": raw.get("version"),
                "sdk_version": None,
                "cwd": raw.get("cwd"),
                "entrypoint": raw.get("entrypoint"),
                "permission_mode": raw.get("permissionMode"),
                "git_branch": raw.get("gitBranch"),
                "occurrence": 1,
                "imported_from": path,
                "source": "session_jsonl",
            }
            model = _first_model(lines)
            if model:
                data["model"] = model
            return TraceEvent(type="init", session_id=raw.get("sessionId"),
                              t=raw.get("timestamp"), data=data)
    return None


def _first_model(lines: list[dict[str, Any]]) -> str | None:
    for raw in lines:
        message = raw.get("message")
        if isinstance(message, dict) and isinstance(message.get("model"), str):
            return message["model"]
    return None


def _blocks_to_events(raw: dict[str, Any], *, role: str, turn: int) -> list[TraceEvent]:
    """A session `message.content` into the same events the SDK loader makes."""
    message = raw.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    events: list[TraceEvent] = []

    if isinstance(content, str):
        if role == "user":
            events.append(TraceEvent(type="user", data={"text": content, "turn": turn}))
        else:
            events.append(TraceEvent(type="assistant_text", data={
                "text": content, "model": message.get("model"),
                "message_id": message.get("id"), "uuid": raw.get("uuid"),
                "stop_reason": message.get("stop_reason")}))
        return events

    for block in content or []:
        if not isinstance(block, dict):
            continue
        kind = str(block.get("type") or "")
        if kind == "text":
            if role == "user":
                events.append(TraceEvent(type="user", data={
                    "text": block.get("text") or "", "turn": turn}))
            else:
                events.append(TraceEvent(type="assistant_text", data={
                    "text": block.get("text") or "", "model": message.get("model"),
                    "message_id": message.get("id"), "uuid": raw.get("uuid"),
                    "stop_reason": message.get("stop_reason")}))
        elif kind == "thinking":
            thinking = block.get("thinking") or block.get("text") or ""
            events.append(TraceEvent(type="thinking", data={"chars": len(str(thinking))}))
        elif kind == "tool_use":
            tool = str(block.get("name") or "")
            events.append(TraceEvent(type="tool_use", data={
                "tool": tool, "id": block.get("id"), "input": block.get("input") or {},
                "parent_tool_use_id": raw.get("parentToolUseId"),
                "synthetic": tool in SYNTHETIC_TOOLS}))
        elif kind == "tool_result":
            body = block.get("content")
            text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False) \
                if body is not None else ""
            data: dict[str, Any] = {
                "tool_use_id": block.get("tool_use_id"),
                "is_error": block.get("is_error"),
                "content_chars": len(text),
                "content": text[:CONTENT_TRUNCATION],
            }
            # UNMEASURED key (CONTRACTS §11 gap 1): read it, never require it.
            if "toolUseResult" in raw:
                data["tool_use_result"] = raw["toolUseResult"]
            events.append(TraceEvent(type="tool_result", data=data))
        else:
            events.append(TraceEvent(type="system", data={
                "subtype": f"content_block:{kind or 'unknown'}",
                "data": {k: v for k, v in block.items() if k != "type"}}))
    return events


def _summarize_bookkeeping(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep a bookkeeping line's identity without carrying 59 KB of payload."""
    keep: dict[str, Any] = {}
    for key, value in raw.items():
        if key in ("type", "sessionId", "timestamp", "cwd", "version", "gitBranch",
                   "userType", "entrypoint", "isSidechain"):
            continue
        if key == "attachment" and isinstance(value, dict):
            keep["attachment_type"] = value.get("type")
            keep["attachment_keys"] = sorted(value)
            continue
        if isinstance(value, str) and len(value) > 200:
            keep[key] = value[:200] + f"… ({len(value)} chars)"
        elif isinstance(value, (dict, list)):
            keep[key] = f"<{type(value).__name__} of {len(value)}>"
        else:
            keep[key] = value
    return keep


# ---------------------------------------------------------------------------
# readers
# ---------------------------------------------------------------------------

def events_of(events: Iterable[TraceEvent], *types: str) -> list[TraceEvent]:
    wanted = set(types)
    return [event for event in events if event.type in wanted]


def tool_calls(events: Iterable[TraceEvent], *, include_synthetic: bool = False) -> list[TraceEvent]:
    """Every `tool_use` event, synthetic ones excluded by default.

    `StructuredOutput` is fabricated by the CLI for `output_format` results, so
    including it would give every structured-output case a phantom call — and
    make `no_tool` fail on a case that called nothing.
    """
    calls = events_of(events, "tool_use")
    if include_synthetic:
        return calls
    return [call for call in calls if not call.synthetic]


def tool_names(events: Iterable[TraceEvent], *, include_synthetic: bool = False) -> list[str]:
    return [call.tool or "" for call in tool_calls(events, include_synthetic=include_synthetic)]


def tool_results(events: Iterable[TraceEvent]) -> list[TraceEvent]:
    return events_of(events, "tool_result")


def tool_errors(events: Iterable[TraceEvent]) -> list[TraceEvent]:
    """Tool results that came back as errors.

    `is_error` is `null` on success, not `False`, so this tests truthiness. A
    check written as `is_error is False` finds nothing, ever.
    """
    return [event for event in tool_results(events) if event.is_error]


def assistant_texts(events: Iterable[TraceEvent]) -> list[str]:
    return [event.text for event in events_of(events, "assistant_text") if event.text]


def final_text(events: Iterable[TraceEvent]) -> str:
    """The agent's last message, which is what a `final_text` grader reads.

    Preference order: the `result` event's `result_text` (authoritative, and
    present even when the last assistant message was a tool call), then the last
    `assistant_text`.
    """
    result = result_event(events)
    if result is not None:
        text = result.get("result_text")
        if isinstance(text, str) and text.strip():
            return text
    texts = assistant_texts(events)
    return texts[-1] if texts else ""


def result_event(events: Iterable[TraceEvent]) -> TraceEvent | None:
    """The last `result` event, or None on imported evidence.

    None is the load-bearing case: a session file has no result line, so cost,
    `num_turns` and `terminal_reason` are unavailable and the graders that read
    them must report NOT_EVALUATED rather than FAILED.
    """
    found = events_of(events, "result")
    return found[-1] if found else None


def init_event(events: Iterable[TraceEvent]) -> TraceEvent | None:
    """The first `init` event.

    `init` may appear more than once — one per turn in a streaming session — so
    the events carry an `occurrence` and this returns the first.
    """
    found = events_of(events, "init")
    return found[0] if found else None


def rate_limit_events(events: Iterable[TraceEvent]) -> list[TraceEvent]:
    """Every rate-limit event.

    Note that their presence is not a problem: one fired on every measured run at
    `allowed_warning`. Only `status == "rejected"` stops a run.
    """
    return events_of(events, "rate_limit")


def hook_events(events: Iterable[TraceEvent], *, event: str | None = None) -> list[TraceEvent]:
    """Hook events, optionally for one hook event name."""
    found = events_of(events, "hook")
    if event is None:
        return found
    return [e for e in found if str(e.get("event") or "") == event]


def subagent_events(events: Iterable[TraceEvent]) -> list[TraceEvent]:
    return events_of(events, "subagent")


def thinking_chars(events: Iterable[TraceEvent]) -> int:
    total = 0
    for event in events_of(events, "thinking"):
        value = event.get("chars")
        if isinstance(value, int):
            total += value
    return total


def turns(events: Iterable[TraceEvent]) -> int:
    """User turns in the evidence, counted from `user` events."""
    return len(events_of(events, "user"))


def has_result(events: Iterable[TraceEvent]) -> bool:
    return result_event(events) is not None


def is_imported(events: Iterable[TraceEvent]) -> bool:
    """Was this evidence imported from a session file rather than instrumented?"""
    init = init_event(events)
    return bool(init and init.get("source") == "session_jsonl")


def to_summary(events: Sequence[TraceEvent]) -> dict[str, Any]:
    """A short, printable description of one run's evidence.

    This is the shape `analyze_trace.py` reports and `agent-debug` reads out, so
    it states what is *missing* as plainly as what is present: `has_result: false`
    is the difference between "the agent stayed under budget" and "nobody knows".
    """
    init = init_event(events)
    result = result_event(events)
    calls = tool_calls(events)
    errors = tool_errors(events)
    limits = rate_limit_events(events)
    summary: dict[str, Any] = {
        "events": len(events),
        "by_type": _counts(event.type for event in events),
        "turns": turns(events),
        "tool_calls": len(calls),
        "tools": _counts(call.tool or "?" for call in calls),
        "synthetic_tool_calls": len(tool_calls(events, include_synthetic=True)) - len(calls),
        "tool_errors": len(errors),
        "thinking_chars": thinking_chars(events),
        "final_text_chars": len(final_text(events)),
        "has_result": result is not None,
        "imported": is_imported(events),
    }
    if init is not None:
        summary["init"] = {
            "model": init.get("model"),
            "cli_version": init.get("cli_version"),
            "sdk_version": init.get("sdk_version"),
            "api_key_source": init.get("api_key_source"),
            "permission_mode": init.get("permission_mode"),
            "tools": init.get("tools") or [],
            "mcp_servers": init.get("mcp_servers") or [],
            "cwd": init.get("cwd"),
            "entrypoint": init.get("entrypoint"),
            "occurrences": len(events_of(events, "init")),
        }
        # Recorded by the 0.1.3 runner when the CLI sends them (CONTRACTS 14.4);
        # absent on older traces and imported sessions, never required.
        for key in ("capabilities", "fast_mode_state", "fast_mode_disabled_reason"):
            if init.get(key) is not None:
                summary["init"][key] = init.get(key)
    if result is not None:
        usage = result.get("usage") or {}
        summary["result"] = {
            "imported_cost": bool(result.get("imported_cost")),
            "models_billed": result.get("models_billed") or sorted(result.get("model_usage") or {}),
            "subtype": result.get("subtype"),
            "terminal_reason": result.get("terminal_reason"),
            "is_error": bool(result.get("is_error")),
            "num_turns": result.get("num_turns"),
            "duration_ms": result.get("duration_ms"),
            "total_cost_usd": result.get("total_cost_usd"),
            "cost_delta_usd": result.get("cost_delta_usd"),
            "cost_basis": result.get("cost_basis"),
            "usage": usage if isinstance(usage, dict) else {},
            "structured_output": result.get("structured_output"),
            "api_error_status": result.get("api_error_status"),
        }
        if result.get("imported_cost"):
            # The cost is real; the terminal state and the structured output are
            # simply not in a `cost-state` line, so they stay undecidable.
            summary["not_evaluated"] = ["terminal", "structured_output"]
            summary["not_evaluated_reason"] = (
                "the result was synthesised from an imported session's `cost-state` line: it "
                "carries the cost but no subtype, terminal_reason or num_turns"
            )
    else:
        summary["not_evaluated"] = [
            "budget", "terminal", "structured_output",
        ]
        summary["not_evaluated_reason"] = (
            "no result event: imported session evidence carries no cost, num_turns or "
            "terminal_reason"
        )
    if limits:
        last = limits[-1]
        summary["rate_limit"] = {
            "status": last.get("status"),
            "kind": last.get("kind"),
            "utilization": last.get("utilization"),
            "resets_at": last.get("resets_at"),
            "windows": last.get("windows") or {},
            "events": len(limits),
        }
    hooks = hook_events(events)
    if hooks:
        summary["hooks"] = _counts(str(h.get("event") or "?") for h in hooks)
    subagents = subagent_events(events)
    if subagents:
        summary["subagents"] = _counts(str(s.get("agent") or "?") for s in subagents)
    unknown = [
        str(e.get("unknown_type")) for e in events_of(events, "system") if e.get("unknown_type")
    ]
    if unknown:
        summary["unknown_event_types"] = sorted(set(unknown))
    return summary


def _counts(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def known_tool_names(events: Iterable[TraceEvent]) -> set[str]:
    """The tools this run actually had, from `init.tools` plus the mcp servers.

    Used by the unknown-tool signature: a call to something outside this set is
    the model inventing a capability, which is a different failure from calling
    the wrong real tool.
    """
    init = init_event(events)
    if init is None:
        return set()
    names = {str(t) for t in (init.get("tools") or []) if isinstance(t, str)}
    names |= {normalize_tool_name(name) for name in names}
    return names
