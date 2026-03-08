"""
Contract utilities — single source of truth for LLM output validation.

Adapted from Forge's contract system. One Python dict drives both
the Markdown prompt (what LLM sees) and the validation (what Python enforces).

LLM produces structured JSON per contract → Python validates → Python saves to DB.
LLM never writes to DB directly.
"""

import json
from typing import Any

from backend.config import DOMAINS


def render_contract(name: str, spec: dict) -> str:
    """Render a contract spec as Markdown for LLM consumption."""
    lines = [f"## {name} Contract", "", "Input: JSON **object** (single item).", ""]

    # Field table
    lines.append("| Field | Type | Required | Values |")
    lines.append("|-------|------|----------|--------|")

    types_map = spec.get("types", {})

    for field in spec.get("required", []):
        type_label = _type_label(types_map.get(field, str))
        values = _enum_values(spec, field)
        lines.append(f"| {field} | {type_label} | YES | {values} |")

    for field in spec.get("optional", []):
        type_label = _type_label(types_map.get(field, str))
        values = _enum_values(spec, field)
        lines.append(f"| {field} | {type_label} | no | {values} |")

    # Invariants
    inv_texts = spec.get("invariant_texts", [])
    if inv_texts:
        lines.extend(["", "### Rules"])
        for inv in inv_texts:
            lines.append(f"- {inv}")

    # Output format
    lines.extend([
        "", "### Output Format",
        "- Output MUST be a raw JSON object only.",
        "- Do NOT wrap in ```json``` code blocks.",
        "- No markdown. No prose. No explanation.",
    ])

    # Notes
    notes = spec.get("notes", "")
    if notes:
        lines.extend(["", notes])

    # Example
    example = spec.get("example")
    if example:
        lines.extend(["", "### Example", "```json",
                       json.dumps(example, indent=2, ensure_ascii=False), "```"])

    return "\n".join(lines)


def validate_contract(spec: dict, data: Any) -> list[str]:
    """Validate data against contract spec. Returns list of error strings (empty = valid)."""
    errors = []

    if not isinstance(data, dict):
        return ["Input must be a JSON object"]

    required = spec.get("required", [])
    enums = spec.get("enums", {})
    types_map = spec.get("types", {})
    invariants = spec.get("invariants", [])

    # Required fields
    for field in required:
        if field not in data:
            errors.append(f"missing required field '{field}'")
        elif data[field] is None:
            errors.append(f"'{field}' cannot be null")

    # Enum validation
    for field, valid_values in enums.items():
        if field in data and data[field] is not None:
            val = data[field]
            # For list fields, check each element
            if isinstance(val, list):
                for v in val:
                    if v not in valid_values:
                        errors.append(f"invalid {field} value '{v}' (not in allowed set)")
            elif val not in valid_values:
                errors.append(
                    f"invalid {field}='{val}' "
                    f"(must be: {', '.join(str(v) for v in sorted(valid_values, key=str))})"
                )

    # Type validation
    for field, expected_type in types_map.items():
        if field in data and data[field] is not None:
            if not isinstance(data[field], expected_type):
                errors.append(
                    f"'{field}' must be {expected_type.__name__}, "
                    f"got {type(data[field]).__name__}"
                )

    # Range validation for scores
    for field in required + spec.get("optional", []):
        if field.startswith("score_") and field in data:
            val = data[field]
            if isinstance(val, (int, float)):
                if val < 0 or val > 100:
                    errors.append(f"'{field}' must be 0-100, got {val}")

    # Per-item invariants
    for check_fn, err_msg in invariants:
        try:
            if not check_fn(data):
                errors.append(err_msg)
        except Exception as e:
            errors.append(f"invariant check failed: {e}")

    return errors


# ---------------------------------------------------------------------------
# Enrichment contract
# ---------------------------------------------------------------------------

# Allow suggested domains + any kebab-case string (validated loosely)
_domain_set = set(DOMAINS)

ENRICHMENT_CONTRACT = {
    "required": [
        "domains", "tags", "summary",
        "strengths", "weaknesses", "use_cases",
        "score_quality", "score_usefulness", "score_novelty",
        "score_description", "score_reusability",
    ],
    "optional": [],
    "types": {
        "domains": list,
        "tags": list,
        "summary": str,
        "strengths": list,
        "weaknesses": list,
        "use_cases": list,
        "score_quality": (int, float),
        "score_usefulness": (int, float),
        "score_novelty": (int, float),
        "score_description": (int, float),
        "score_reusability": (int, float),
    },
    "invariants": [
        (lambda d: 1 <= len(d.get("domains", [])) <= 3,
         "domains must have 1-3 entries"),
        (lambda d: len(d.get("tags", [])) == 5,
         "tags must have exactly 5 entries"),
        (lambda d: len(d.get("strengths", [])) == 3,
         "strengths must have exactly 3 entries"),
        (lambda d: len(d.get("weaknesses", [])) >= 1,
         "weaknesses must have at least 1 entry"),
        (lambda d: len(d.get("use_cases", [])) == 3,
         "use_cases must have exactly 3 entries"),
        (lambda d: 10 <= len(d.get("summary", "")) <= 500,
         "summary must be 10-500 characters"),
        (lambda d: all(isinstance(s, str) and len(s) > 5 for s in d.get("strengths", [])),
         "each strength must be a descriptive string (>5 chars)"),
        (lambda d: all(isinstance(t, str) and "-" not in t or len(t) < 30 for t in d.get("tags", [])),
         "tags should be short keywords"),
    ],
    "invariant_texts": [
        "domains: 1-3 entries from the suggested list (or new kebab-case domain if none fits)",
        "tags: exactly 5 short keyword tags",
        "summary: 2-3 concise sentences, 10-500 characters",
        "strengths: exactly 3 descriptive strings",
        "weaknesses: 1-2 descriptive strings",
        "use_cases: exactly 3 practical scenarios",
        "score_*: integer 0-100, be critical — 80+ is exceptional, 40-60 is average, <30 is poor",
    ],
    "example": {
        "domains": ["security", "testing"],
        "tags": ["fuzzing", "vulnerability", "automated", "security-audit", "binary-analysis"],
        "summary": "Automates fuzz testing of C/C++ binaries using AFL++. Detects memory corruption vulnerabilities by generating and mutating test inputs. Best used in CI pipelines for security-critical codebases.",
        "strengths": [
            "Clear step-by-step instructions for setting up AFL++ campaigns",
            "Includes corpus management and crash triage procedures",
            "Well-structured with separate sections for different fuzzing strategies"
        ],
        "weaknesses": [
            "Limited to C/C++ targets, no guidance for other languages",
            "Missing examples for network protocol fuzzing"
        ],
        "use_cases": [
            "Running automated fuzz tests in CI for a C library",
            "Triaging crashes found during a security audit",
            "Setting up a persistent fuzzing campaign for a parser"
        ],
        "score_quality": 72,
        "score_usefulness": 68,
        "score_novelty": 55,
        "score_description": 65,
        "score_reusability": 45
    },
    "notes": """### Scoring Guide

| Score | Meaning | When to give |
|-------|---------|-------------|
| 80-100 | Exceptional | Top-tier clarity, unique approach, production-ready |
| 60-79 | Good | Solid skill, well-documented, clearly useful |
| 40-59 | Average | Works but generic, missing examples, narrow scope |
| 20-39 | Below average | Vague instructions, limited value, mostly boilerplate |
| 0-19 | Poor | Broken, empty, copy-paste, no real content |

Be honest and critical. Most skills should score 30-60. Reserve 80+ for truly exceptional work.""",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _type_label(t) -> str:
    if isinstance(t, tuple):
        return "/".join(_type_label(x) for x in t)
    labels = {str: "string", int: "int", float: "number",
              bool: "boolean", list: "array", dict: "object"}
    return labels.get(t, "string")


def _enum_values(spec: dict, field: str) -> str:
    enums = spec.get("enums", {})
    if field in enums:
        vals = sorted(str(v) for v in enums[field] if v is not None)
        return ", ".join(vals)
    return ""
