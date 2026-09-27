"""Text graders: `regex` and `final_text`.

Both read the agent's words, not its actions, so both are cheap and both are
easy to over-trust: a `regex` that passes on the word "sorry" proves the model
apologised, not that it refused. The grader body is where a case says which of
the two it meant.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import Evidence, GraderResult, not_evaluated, verdict

_FLAG_NAMES = {
    "i": re.IGNORECASE, "ignorecase": re.IGNORECASE,
    "m": re.MULTILINE, "multiline": re.MULTILINE,
    "s": re.DOTALL, "dotall": re.DOTALL,
    "x": re.VERBOSE, "verbose": re.VERBOSE,
    "a": re.ASCII, "ascii": re.ASCII,
}

TEXT_SUFFIXES = (".txt", ".md", ".json", ".jsonl", ".csv", ".yaml", ".yml", ".py", ".log", ".html")


def parse_flags(raw: Any) -> int:
    if raw in (None, "", []):
        return 0
    names = raw if isinstance(raw, list) else re.split(r"[,\s|]+", str(raw))
    flags = 0
    for name in names:
        key = str(name).strip().lower()
        if key:
            flags |= _FLAG_NAMES.get(key, 0)
    return flags


def target_text(target: Any, evidence: Evidence) -> tuple[str | None, str]:
    """Return (text, why-it-is-missing). `None` means NOT_EVALUATED."""
    name = target or "last_message"
    if isinstance(name, dict):  # {source: file, path: ...}
        base = evidence.run_cwd or evidence.case_dir or Path(".")
        path = base / str(name.get("path", ""))
        if not path.is_file():
            return None, f"no such file for the grader target: {path}"
        return path.read_text(encoding="utf-8", errors="replace"), ""
    if name == "last_message":
        return evidence.last_message, ""
    if name == "trace":
        return "\n".join(json.dumps(e, default=str) for e in evidence.events), ""
    if name == "mock_calls":
        return json.dumps(evidence.mock_calls, default=str, indent=2), ""
    if name == "files":
        if evidence.run_cwd is None or not evidence.run_cwd.is_dir():
            return None, "the run has no working directory to read files from"
        chunks: list[str] = []
        for path in sorted(evidence.run_cwd.rglob("*")):
            if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
                try:
                    chunks.append(f"# {path.relative_to(evidence.run_cwd)}\n"
                                  + path.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    continue
        return "\n".join(chunks), ""
    if name == "simulated_user":
        return "\n".join(evidence.simulated_user_turns), ""
    return None, f"unknown grader target {name!r}"


def grade_regex(grader: Any, evidence: Evidence) -> GraderResult:
    text, why = target_text(grader.get("target"), evidence)
    if text is None:
        return not_evaluated(grader, why)
    pattern = re.compile(str(grader.get("pattern")), parse_flags(grader.get("flags")))
    matches = pattern.findall(text)
    count = len(matches)
    mode = str(grader.get("match") or "contains")
    if mode == "contains":
        return verdict(grader, count > 0, f"{count} match(es) for /{pattern.pattern}/")
    if mode == "not_contains":
        return verdict(grader, count == 0,
                       f"{count} match(es) for /{pattern.pattern}/ (expected none)"
                       + (f"; first: {matches[0]!r}" if matches else ""))
    if mode.startswith("count:"):
        try:
            wanted = int(mode.split(":", 1)[1])
        except ValueError:
            return not_evaluated(grader, f"match: {mode!r} is not `count:<int>`")
        return verdict(grader, count == wanted, f"{count} match(es), expected exactly {wanted}")
    return not_evaluated(grader, f"unknown match mode {mode!r}")


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def rouge1(candidate: str, reference: str) -> float:
    """Unigram F1. No dependency, and honest about what it measures: word overlap."""
    cand, ref = _tokens(candidate), _tokens(reference)
    if not cand or not ref:
        return 0.0
    from collections import Counter

    overlap = Counter(cand) & Counter(ref)
    hits = sum(overlap.values())
    if not hits:
        return 0.0
    precision = hits / len(cand)
    recall = hits / len(ref)
    return 2 * precision * recall / (precision + recall)


def grade_final_text(grader: Any, evidence: Evidence) -> GraderResult:
    text, why = target_text(grader.get("target") or "last_message", evidence)
    if text is None:
        return not_evaluated(grader, why)
    reference = str(grader.get("reference") or "")
    mode = str(grader.get("mode") or "contains")
    if mode == "exact":
        ok = text.strip() == reference.strip()
        return verdict(grader, ok, "exact match" if ok else f"differs from the reference ({len(text)} chars)")
    if mode == "contains":
        ok = reference.strip().lower() in text.lower()
        return verdict(grader, ok, f"reference {'found' if ok else 'not found'} in the final text")
    if mode == "rouge1":
        threshold = float(grader.get("threshold") or 0.5)
        score = rouge1(text, reference)
        return verdict(grader, score >= threshold,
                       f"rouge1 {score:.3f} against a threshold of {threshold:.3f}", score=score)
    return not_evaluated(grader, f"unknown final_text mode {mode!r}")
