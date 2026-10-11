"""`structured_output`: validate `ResultMessage.structured_output`.

The schema check is a deliberately small hand-rolled subset of JSON Schema —
`type`, `required`, `properties`, `items`, `enum`, `minimum`/`maximum`,
`minItems`/`maxItems` — because the runner ships into projects that may not have
`jsonschema` installed and may not want it. A schema this subset cannot express
is a sign the case is asserting too much in one grader; `equals` and `contains`
cover the rest.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import Evidence, GraderResult, not_evaluated, verdict

_TYPES: dict[str, Any] = {
    "object": dict, "array": list, "string": str, "number": (int, float),
    "integer": int, "boolean": bool, "null": type(None),
}


def validate(value: Any, schema: Any, path: str = "$") -> list[str]:
    """Return a list of human-readable violations; empty means valid."""
    if not isinstance(schema, dict):
        return []
    problems: list[str] = []
    declared = schema.get("type")
    types = [declared] if isinstance(declared, str) else list(declared or [])
    if types:
        expected = tuple(t for name in types for t in _as_tuple(_TYPES.get(name, object)))
        # JSON has no separate int/bool, but Python does: a bool is not a number here.
        if isinstance(value, bool) and "boolean" not in types:
            problems.append(f"{path}: expected {'/'.join(types)}, got boolean")
        elif not isinstance(value, expected):
            problems.append(f"{path}: expected {'/'.join(types)}, got {type(value).__name__}")
            return problems
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{path}: {value!r} is not one of {schema['enum']}")
    if isinstance(value, dict):
        for key in schema.get("required") or []:
            if key not in value:
                problems.append(f"{path}: missing required property {key!r}")
        for key, sub in (schema.get("properties") or {}).items():
            if key in value:
                problems.extend(validate(value[key], sub, f"{path}.{key}"))
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(schema.get("properties") or {}))
            if extra:
                problems.append(f"{path}: unexpected propert(ies) {', '.join(extra)}")
    if isinstance(value, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                problems.extend(validate(item, items, f"{path}[{index}]"))
        if "minItems" in schema and len(value) < schema["minItems"]:
            problems.append(f"{path}: {len(value)} item(s), minItems is {schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            problems.append(f"{path}: {len(value)} item(s), maxItems is {schema['maxItems']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            problems.append(f"{path}: {value} is below the minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            problems.append(f"{path}: {value} is above the maximum {schema['maximum']}")
    return problems


def _as_tuple(value: Any) -> tuple[Any, ...]:
    return value if isinstance(value, tuple) else (value,)


def _load_schema(grader: Any, evidence: Evidence) -> tuple[Any, str]:
    inline = grader.get("schema")
    if isinstance(inline, dict):
        return inline, ""
    if isinstance(inline, str) and inline.strip().startswith("{"):
        try:
            return json.loads(inline), ""
        except json.JSONDecodeError as exc:
            return None, f"inline `schema` is not valid JSON: {exc}"
    name = grader.get("schema_file") or (inline if isinstance(inline, str) else None)
    if not name:
        return None, "neither `schema` nor `schema_file` is usable"
    bases = [p for p in (evidence.case_dir, grader.path.parent if hasattr(grader, "path") else None) if p]
    for base in bases:
        path = Path(base) / str(name)
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8")), ""
            except (OSError, json.JSONDecodeError) as exc:
                return None, f"{path}: {exc}"
    return None, f"no schema file {name!r} beside the case"


def grade_structured_output(grader: Any, evidence: Evidence) -> GraderResult:
    if evidence.result is None:
        return not_evaluated(grader, "the run produced no result message, so there is no structured output")
    if evidence.result.get("imported_cost"):
        return not_evaluated(
            grader,
            "the result was synthesised from an imported session's `cost-state` line, which "
            "carries the session cost and no structured output",
        )
    value = evidence.structured_output
    if value is None:
        return verdict(grader, False,
                       "`structured_output` is null — the agent's options set no `output_format`, "
                       "or the model did not produce one")
    schema, why = _load_schema(grader, evidence)
    problems: list[str] = []
    if schema is None:
        return not_evaluated(grader, why)
    problems.extend(validate(value, schema))
    equals = grader.get("equals")
    if equals is not None:
        parsed = json.loads(equals) if isinstance(equals, str) and equals.strip().startswith(("{", "[")) else equals
        if value != parsed:
            problems.append(f"$: {value!r} != the expected {parsed!r}")
    contains = grader.get("contains")
    if contains is not None:
        from .tools import _subset

        parsed = json.loads(contains) if isinstance(contains, str) and contains.strip().startswith("{") else contains
        if not _subset(parsed, value):
            problems.append(f"$: {parsed!r} is not contained in {value!r}")
    return verdict(grader, not problems,
                   "structured output matches" if not problems else "; ".join(problems[:6]))
