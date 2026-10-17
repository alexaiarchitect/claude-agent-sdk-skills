"""Turn the SDK's message stream into trace events (CONTRACTS section 5).

The mapping is duck-typed on attribute names rather than `isinstance` against
the SDK's classes, for three reasons measured in P-1: `SystemMessage` has six
subclasses that must all stay `system` events, `HookEventMessage` arrives as a
`SystemMessage` subtype on the wire, and the runner must keep working when the
SDK adds a message type it has never heard of. An unknown message becomes a
`system` event carrying what it had; nothing is ever dropped silently.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from . import RATE_LIMIT_STATUSES, SCHEMA_TRACE, SYNTHETIC_TOOLS

TOOL_RESULT_CONTENT_LIMIT = 2048


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _truncate(text: str, limit: int = TOOL_RESULT_CONTENT_LIMIT) -> str:
    return text if len(text) <= limit else text[:limit] + f"…(+{len(text) - limit} chars)"


def _as_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")) or json.dumps(item, default=str))
            else:
                parts.append(str(item))
        return "\n".join(p for p in parts if p)
    return json.dumps(content, default=str)


def flatten_usage(usage: dict[str, Any] | None) -> dict[str, Any]:
    """The flat projection graders read. `cache_creation` is a nested dict of
    ephemeral TTL buckets, never a number, so it stays out of the flat view."""
    usage = usage or {}
    details = usage.get("output_tokens_details") or {}
    server = usage.get("server_tool_use") or {}
    return {
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
        "thinking_tokens": details.get("thinking_tokens", 0),
        "web_search_requests": server.get("web_search_requests", 0),
        "web_fetch_requests": server.get("web_fetch_requests", 0),
        "service_tier": usage.get("service_tier"),
        "speed": usage.get("speed"),
    }


def rate_limit_payload(info: Any, *, kind: str = "rate_limit", message: str = "") -> dict[str, Any]:
    """Normalize a `RateLimitInfo` (or a plain dict) to the trace shape.

    The dataclass is snake_case but the wire keys inside `.raw` are camelCase,
    and `raw` carries two fields the dataclass does not model at all:
    `surpassedThreshold` and `unifiedWindows`. `unifiedWindows` is the honest
    "how close am I" source — better than the single top-level utilization.
    """
    get = (lambda name, default=None: info.get(name, default)) if isinstance(info, dict) \
        else (lambda name, default=None: getattr(info, name, default))
    raw = get("raw") or {}
    if not isinstance(raw, dict):
        raw = {}
    windows = raw.get("unifiedWindows") or {}
    normalized_windows = {
        name: {
            "utilization": w.get("utilization"),
            "resets_at": w.get("resetsAt", w.get("resets_at")),
        }
        for name, w in windows.items() if isinstance(w, dict)
    }
    status = get("status")
    return {
        "kind": kind,
        "status": status if status in RATE_LIMIT_STATUSES else (status or "allowed"),
        "rate_limit_type": get("rate_limit_type"),
        "utilization": get("utilization"),
        "resets_at": get("resets_at"),
        "surpassed_threshold": raw.get("surpassedThreshold"),
        "windows": normalized_windows,
        "overage_status": get("overage_status"),
        "overage_resets_at": get("overage_resets_at"),
        "overage_disabled_reason": get("overage_disabled_reason"),
        "message": message,
        "raw": raw,
    }


#: Text that marks an error result as a usage-limit hit rather than a plain
#: failure. There is no SDK message type for it (CONTRACTS gap 2), so the runner
#: classifies it from the result text and `api_error_status`.
USAGE_LIMIT_MARKERS = (
    "usage limit", "usage_limit", "rate limit", "rate_limit", "too many requests",
    "quota", "429", "limit reached", "resets at",
)


def looks_like_usage_limit(text: str | None, api_error_status: int | None = None) -> bool:
    if api_error_status == 429:
        return True
    lowered = (text or "").lower()
    return any(marker in lowered for marker in USAGE_LIMIT_MARKERS)


@dataclass
class Capture:
    """Accumulates trace events plus the evidence graders need."""

    run_id: str
    case: str
    session_id: str | None = None
    include_thinking: bool = False
    #: `"agent"` or `"runner-default"`: who decided `permission_mode` for this
    #: session (CONTRACTS section 13.1). Recorded on the `init` event, because the
    #: mode the CLI reports there does not say whether anyone chose it on purpose.
    permission_mode_source: str | None = None

    events: list[dict[str, Any]] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    init_count: int = 0
    turn: int = 0
    hook_events_installed: set[str] = field(default_factory=set)
    rate_limit: dict[str, Any] | None = None
    rejected_rate_limit: dict[str, Any] | None = None
    _last_total_cost: float = 0.0
    _assistant_texts: list[str] = field(default_factory=list)

    # -- writing --------------------------------------------------------
    def emit(self, type_: str, **fields: Any) -> dict[str, Any]:
        event: dict[str, Any] = {
            "i": len(self.events),
            "t": _now(),
            "type": type_,
            "run_id": self.run_id,
            "case": self.case,
            "session_id": self.session_id,
        }
        if not self.events:
            event = {"schema": SCHEMA_TRACE, **event}
        event.update(fields)
        self.events.append(event)
        return event

    def user_turn(self, text: str) -> None:
        self.turn += 1
        self.emit("user", text=text, turn=self.turn)

    def note(self, message: str, **fields: Any) -> None:
        self.emit("system", subtype="runner_note", data={"message": message, **fields})

    def hook(self, event: str, phase: str, **fields: Any) -> None:
        self.emit("hook", event=event, phase=phase, **fields)

    # -- reading --------------------------------------------------------
    @property
    def last_message(self) -> str:
        return self._assistant_texts[-1] if self._assistant_texts else ""

    @property
    def assistant_texts(self) -> list[str]:
        return list(self._assistant_texts)

    def tool_uses(self, *, include_synthetic: bool = False) -> list[dict[str, Any]]:
        return [
            e for e in self.events
            if e["type"] == "tool_use" and (include_synthetic or not e.get("synthetic"))
        ]

    def tool_results(self) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] == "tool_result"]

    def hook_records(self) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] == "hook"]

    @property
    def result(self) -> dict[str, Any] | None:
        return self.results[-1] if self.results else None

    @property
    def total_cost_usd(self) -> float:
        """The case total: the last running total the session reported."""
        return float(self.results[-1].get("total_cost_usd") or 0.0) if self.results else 0.0

    def to_jsonl(self) -> str:
        return "".join(json.dumps(e, default=str) + "\n" for e in self.events)

    # -- the mapping ----------------------------------------------------
    def add(self, message: Any) -> None:
        """Map one SDK message onto zero or more trace events."""
        session_id = getattr(message, "session_id", None)
        if session_id and not self.session_id:
            self.session_id = session_id

        # A `SystemMessage` and every subclass of it: `init`, the hook-event
        # wire form, the Task* lifecycle messages, and anything unrecognised.
        if hasattr(message, "subtype") and hasattr(message, "data") and not hasattr(message, "num_turns"):
            self._add_system(message)
            return
        if hasattr(message, "rate_limit_info"):
            payload = rate_limit_payload(message.rate_limit_info)
            self.rate_limit = payload
            if payload.get("status") == "rejected":
                self.rejected_rate_limit = payload
            self.emit("rate_limit", **payload)
            return
        if hasattr(message, "new_conversation_id"):
            self.emit("conversation_reset", new_conversation_id=message.new_conversation_id)
            return
        if hasattr(message, "num_turns") and hasattr(message, "subtype"):
            self._add_result(message)
            return
        if hasattr(message, "event") and hasattr(message, "uuid"):  # StreamEvent
            self.emit("system", subtype="stream_event", data={"event": getattr(message, "event", None)})
            return
        if hasattr(message, "content"):
            if hasattr(message, "model"):
                self._add_assistant(message)
            else:
                self._add_user(message)
            return
        self.emit("system", subtype=type(message).__name__, data=_describe(message))

    def _add_system(self, message: Any) -> None:
        subtype = getattr(message, "subtype", "") or ""
        data = getattr(message, "data", None) or {}
        if not isinstance(data, dict):
            data = {"value": data}
        if subtype == "init":
            self.init_count += 1
            # Recorded when present, never required (CONTRACTS section 14.4):
            # `capabilities` (CLI 2.1.205+; 11 strings on 2.1.301) is for feature
            # detection instead of version comparison, and the fast-mode pair is
            # declared on `SystemInitData` from SDK 0.2.166. Undeclared keys the
            # CLI also sends (`original_cwd`, `memory_paths`, `view_mode`, ...)
            # are ignored, and `plugins[]` entries are copied as they come
            # (2.1.301 sends `source`, not `version`).
            extras: dict[str, Any] = {}
            capabilities = data.get("capabilities")
            if isinstance(capabilities, list):
                extras["capabilities"] = [str(c) for c in capabilities]
            for key in ("fast_mode_state", "fast_mode_disabled_reason"):
                if data.get(key) is not None:
                    extras[key] = data.get(key)
            self.emit(
                "init",
                model=data.get("model"),
                tools=list(data.get("tools") or []),
                mcp_servers=list(data.get("mcp_servers") or []),
                permission_mode=data.get("permissionMode", data.get("permission_mode")),
                permission_mode_source=self.permission_mode_source,
                cwd=data.get("cwd"),
                cli_version=data.get("claude_code_version"),
                sdk_version=data.get("sdk_version"),
                api_key_source=data.get("apiKeySource"),
                skills=list(data.get("skills") or []),
                plugins=list(data.get("plugins") or []),
                agents=list(data.get("agents") or []),
                occurrence=self.init_count,
                **extras,
            )
            return
        # Anything else (`commands_changed`, sent right after `init` by CLI
        # 2.1.301, among them) falls through to a plain `system` event below.
        if subtype in ("hook_started", "hook_response") or hasattr(message, "hook_event_name"):
            event_name = getattr(message, "hook_event_name", "") or data.get("hook_event") or ""
            self.emit(
                "hook", event=event_name, phase=subtype or "hook_response",
                matcher=data.get("matcher"), tool=data.get("tool_name", data.get("tool")),
                decision=data.get("decision"), data=data,
            )
            return
        self.emit("system", subtype=subtype or type(message).__name__, data=data)

    def _add_assistant(self, message: Any) -> None:
        model = getattr(message, "model", None)
        message_id = getattr(message, "message_id", None)
        uuid = getattr(message, "uuid", None)
        stop_reason = getattr(message, "stop_reason", None)
        parent = getattr(message, "parent_tool_use_id", None)
        for block in _blocks(getattr(message, "content", None)):
            kind, payload = _block_kind(block)
            if kind == "text":
                text = payload.get("text", "")
                self._assistant_texts.append(text)
                self.emit("assistant_text", text=text, model=model, message_id=message_id,
                          uuid=uuid, stop_reason=stop_reason)
            elif kind == "thinking":
                thinking = payload.get("thinking", "")
                fields = {"chars": len(thinking)}
                if self.include_thinking:
                    fields["text"] = thinking
                self.emit("thinking", **fields)
            elif kind == "tool_use":
                name = payload.get("name", "")
                self.emit("tool_use", tool=name, id=payload.get("id"),
                          input=payload.get("input") or {}, parent_tool_use_id=parent,
                          synthetic=name in SYNTHETIC_TOOLS)
            elif kind == "server_tool_use":
                self.emit("server_tool_use", tool=payload.get("name", ""), id=payload.get("id"),
                          input=payload.get("input") or {})
            elif kind == "server_tool_result":
                content = payload.get("content")
                self.emit("server_tool_result", tool_use_id=payload.get("tool_use_id"),
                          content_chars=len(_as_text(content)))
            elif kind == "tool_result":
                self._emit_tool_result(payload, None)
            else:
                self.emit("system", subtype="unknown_block", data=payload)

    def _add_user(self, message: Any) -> None:
        content = getattr(message, "content", None)
        tool_use_result = getattr(message, "tool_use_result", None)
        if isinstance(content, str):
            self.turn += 1
            self.emit("user", text=content, turn=self.turn)
            return
        for block in _blocks(content):
            kind, payload = _block_kind(block)
            if kind == "tool_result":
                self._emit_tool_result(payload, tool_use_result)
            elif kind == "text":
                self.turn += 1
                self.emit("user", text=payload.get("text", ""), turn=self.turn)
            else:
                self.emit("system", subtype="unknown_block", data=payload)

    def _emit_tool_result(self, payload: dict[str, Any], tool_use_result: Any) -> None:
        text = _as_text(payload.get("content"))
        rich: Any = tool_use_result
        if isinstance(rich, (dict, list)):
            rich = json.loads(_truncate(json.dumps(rich, default=str))) \
                if len(json.dumps(rich, default=str)) <= TOOL_RESULT_CONTENT_LIMIT \
                else {"truncated": _truncate(json.dumps(rich, default=str))}
        elif isinstance(rich, str):
            rich = _truncate(rich)
        self.emit(
            "tool_result",
            tool_use_id=payload.get("tool_use_id"),
            # Measured: `is_error` is `null` on success, not `False`. Graders
            # must test truthiness; the trace keeps the value verbatim.
            is_error=payload.get("is_error"),
            content_chars=len(text),
            content=_truncate(text),
            tool_use_result=rich,
        )

    def _add_result(self, message: Any) -> None:
        total = getattr(message, "total_cost_usd", None)
        total_f = float(total) if total is not None else self._last_total_cost
        delta = round(total_f - self._last_total_cost, 10)
        self._last_total_cost = total_f
        usage_raw = getattr(message, "usage", None) or {}
        result_text = getattr(message, "result", None)
        api_error_status = getattr(message, "api_error_status", None)
        is_error = bool(getattr(message, "is_error", False))
        model_usage = getattr(message, "model_usage", None) or {}
        if not isinstance(model_usage, dict):
            model_usage = {}
        payload = {
            "subtype": getattr(message, "subtype", None),
            "is_error": is_error,
            "terminal_reason": getattr(message, "terminal_reason", None),
            "stop_reason": getattr(message, "stop_reason", None),
            "num_turns": getattr(message, "num_turns", 0),
            "duration_ms": getattr(message, "duration_ms", 0),
            "duration_api_ms": getattr(message, "duration_api_ms", 0),
            "total_cost_usd": total,
            "cost_delta_usd": delta,
            "usage": flatten_usage(usage_raw),
            "usage_raw": usage_raw,
            "model_usage": model_usage,
            # Every model the session was billed for, not just the agent's:
            # measured 2026-10-11 on CLI 2.1.294 and again 2026-10-17 on 2.1.301,
            # the CLI bills its own background work to `claude-haiku-5-5` unasked,
            # so a cost read that takes the first entry is wrong about the total.
            "models_billed": sorted(model_usage),
            # True when no model reported a negotiated rate: `costBasis` is
            # `list | managed | unknown` and is absent from the `ModelUsage`
            # TypedDict (still on 0.2.168) though the wire carries it, so it is read
            # with `.get()` and absent counts as list pricing.
            "cost_basis_list": all(
                (entry or {}).get("costBasis", "list") == "list"
                for entry in model_usage.values()
            ),
            "structured_output": getattr(message, "structured_output", None),
            "result_text": result_text,
            "permission_denials": getattr(message, "permission_denials", None) or [],
            "deferred_tool_use": getattr(message, "deferred_tool_use", None),
            "errors": getattr(message, "errors", None),
            "api_error_status": api_error_status,
            "session_id": getattr(message, "session_id", None),
            "uuid": getattr(message, "uuid", None),
        }
        self.results.append(payload)
        self.emit("result", **payload)
        if is_error and looks_like_usage_limit(result_text, api_error_status):
            limit = rate_limit_payload(
                {"status": "rejected", "raw": {}}, kind="usage_limit",
                message=(result_text or "")[:400],
            )
            self.rate_limit = limit
            self.rejected_rate_limit = limit
            self.emit("rate_limit", **limit)

    def set_cost_basis(self, basis: str) -> None:
        for result in self.results:
            result["cost_basis"] = basis
        for event in self.events:
            if event["type"] == "result":
                event["cost_basis"] = basis


def _blocks(content: Any) -> list[Any]:
    if content is None:
        return []
    if isinstance(content, (list, tuple)):
        return list(content)
    return [content]


def _block_kind(block: Any) -> tuple[str, dict[str, Any]]:
    """Identify a content block and flatten it to a dict, from the SDK class or a raw dict."""
    if isinstance(block, dict):
        payload = dict(block)
    else:
        payload = {
            name: getattr(block, name)
            for name in ("text", "thinking", "signature", "id", "name", "input",
                         "tool_use_id", "content", "is_error")
            if hasattr(block, name)
        }
    # `ServerToolUseBlock` carries the same three fields as `ToolUseBlock` and
    # `ServerToolResultBlock` the same two as `ToolResultBlock`; the class name
    # is the only discriminator the SDK gives us, so it is checked first.
    class_name = type(block).__name__
    if class_name == "ServerToolUseBlock":
        return "server_tool_use", payload
    if class_name == "ServerToolResultBlock":
        return "server_tool_result", payload
    if "thinking" in payload:
        return "thinking", payload
    if "tool_use_id" in payload:
        return "tool_result", payload
    if "name" in payload and "id" in payload:
        return "tool_use", payload
    if "text" in payload:
        return "text", payload
    return "unknown", payload


def _describe(message: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"class": type(message).__name__}
    for name in dir(message):
        if name.startswith("_"):
            continue
        try:
            value = getattr(message, name)
        except Exception:  # pragma: no cover - defensive against exotic properties
            continue
        if callable(value):
            continue
        out[name] = value if isinstance(value, (str, int, float, bool, type(None))) else str(value)
    return out
