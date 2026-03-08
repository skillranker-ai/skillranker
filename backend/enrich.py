"""
AI enrichment layer — uses Claude to evaluate skills via contract system.

The contract defines EXACTLY what JSON structure LLM must return.
Python validates the response before saving anything to DB.
LLM never writes to DB directly.

Usage:
    python -m backend.enrich
    python -m backend.enrich --limit 10
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from sqlmodel import select

from backend.config import ANTHROPIC_API_KEY, DOMAINS, LLM_MAX_TOKENS, LLM_MODEL
from backend.contracts import ENRICHMENT_CONTRACT, render_contract, validate_contract
from backend.db import get_session, init_db
from backend.models import Skill, SkillStatus


# ---------------------------------------------------------------------------
# Prompt assembly — contract-driven
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an expert evaluator of Claude Code Agent Skills — SKILL.md files that \
teach Claude Code how to perform specific tasks.

You will receive a skill to evaluate and a contract defining the exact JSON \
structure you must return. Follow the contract precisely."""

SCORING_CRITERIA = """\
## Scoring criteria (0-100 each, be critical and honest)

**score_quality** — Instruction clarity & coherence
- Are the instructions clear, well-structured, and unambiguous?
- Would Claude Code execute them correctly without confusion?
- Penalty: vague instructions, contradictions, poor formatting

**score_usefulness** — Practical value for real-world work
- Does this solve an actual problem developers face?
- Is it a toy/demo or production-ready?
- Penalty: trivial tasks, too narrow, already built-in to Claude

**score_novelty** — Uniqueness and originality
- Is this a fresh idea or a copy/rehash of common patterns?
- Penalty: generic boilerplate, copy-paste from docs, bulk-generated

**score_description** — SKILL.md documentation quality
- Does it explain WHAT, WHEN, and HOW?
- Are there examples, edge cases, limitations?
- Penalty: missing description, no examples, wall-of-text

**score_reusability** — Portability across projects
- Can this skill be dropped into any project and work?
- Penalty: hardcoded paths, assumes specific project structure"""

DOMAIN_INSTRUCTION = """\
## Category assignment

Pick 1-3 domains that BEST fit. Be precise — "coding" and "general" are last resorts.

Suggested domains: {domains}

If NONE fits well, create a new one in lowercase-kebab-case (e.g. "bioinformatics")."""


def _build_prompt(skill: Skill) -> str:
    """Assemble the full prompt from contract + skill data."""
    parts = [
        SCORING_CRITERIA,
        "",
        DOMAIN_INSTRUCTION.format(domains=", ".join(DOMAINS)),
        "",
        render_contract("skill-enrichment", ENRICHMENT_CONTRACT),
        "",
        "## Skill to evaluate",
        "",
        f"NAME: {skill.name}",
        f"REPO: {skill.repo_fullname}",
        f"STARS: {skill.stars}",
        f"LICENSE: {skill.license}",
        "",
        "SKILL.md content (first 4000 chars):",
        skill.skill_md_raw[:4000],
        "",
        "README (first 1500 chars):",
        skill.readme_raw[:1500],
    ]

    # Add previous assessment context if re-evaluating
    previous = _build_previous_assessment(skill)
    if previous:
        parts.append(previous)

    return "\n".join(parts)


def _build_previous_assessment(skill: Skill) -> str:
    """Build context of previous assessment for re-evaluation."""
    if not skill.enriched_at or not skill.ai_summary:
        return ""

    return f"""
## Previous assessment (from {skill.enriched_at})

Compare the current SKILL.md with your previous assessment below.
If content changed, adjust scores accordingly with justification.
If unchanged, keep scores consistent (+/- 3 points max).

Previous scores: quality={skill.score_ai_quality:.0f}, \
usefulness={skill.score_ai_usefulness:.0f}, novelty={skill.score_ai_novelty:.0f}, \
description={skill.score_ai_description:.0f}, reusability={skill.score_ai_reusability:.0f}
Previous summary: {skill.ai_summary}
Previous domains: {', '.join(skill.domains)}
Previous strengths: {'; '.join(skill.ai_strengths)}
Previous weaknesses: {'; '.join(skill.ai_weaknesses)}"""


# ---------------------------------------------------------------------------
# Claude API call
# ---------------------------------------------------------------------------

def _call_claude(prompt: str) -> dict | None:
    """Call Claude API and parse JSON response."""
    if not ANTHROPIC_API_KEY:
        print("  No ANTHROPIC_API_KEY — skipping AI enrichment", file=sys.stderr)
        return None

    try:
        import anthropic
    except ImportError:
        print("  anthropic package not installed — pip install anthropic", file=sys.stderr)
        return None

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        response = client.messages.create(
            model=LLM_MODEL,
            max_tokens=LLM_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  JSON parse error: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  Claude API error: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Enrich single skill (contract-validated)
# ---------------------------------------------------------------------------

def enrich_skill(skill: Skill) -> bool:
    """Enrich a single skill. Returns True on success.

    Flow: build prompt from contract → call Claude → validate response
    against contract → only then save fields to skill object.
    """
    prompt = _build_prompt(skill)
    result = _call_claude(prompt)
    if not result:
        return False

    # Validate LLM response against contract BEFORE saving anything
    errors = validate_contract(ENRICHMENT_CONTRACT, result)
    if errors:
        print(f"  Contract validation failed for {skill.name}:", file=sys.stderr)
        for e in errors[:5]:
            print(f"    - {e}", file=sys.stderr)
        return False

    # Contract passed — Python saves validated data to model
    skill.domains = result["domains"]
    skill.tags = result["tags"]
    skill.ai_summary = result["summary"]
    skill.ai_strengths = result["strengths"]
    skill.ai_weaknesses = result["weaknesses"]
    skill.ai_use_cases = result["use_cases"]
    skill.score_ai_quality = float(result["score_quality"])
    skill.score_ai_usefulness = float(result["score_usefulness"])
    skill.score_ai_novelty = float(result["score_novelty"])
    skill.score_ai_description = float(result["score_description"])
    skill.score_ai_reusability = float(result["score_reusability"])

    return True


# ---------------------------------------------------------------------------
# Batch enrichment
# ---------------------------------------------------------------------------

def enrich_all(limit: int = 0) -> int:
    """Enrich evaluated skills. Returns count enriched.

    Smart skip: if skill_md_changed=False and already enriched,
    reuse previous AI scores (no API call).
    """
    session = get_session()
    query = select(Skill).where(Skill.status == SkillStatus.EVALUATED.value)
    if limit > 0:
        query = query.limit(limit)
    skills = session.exec(query).all()

    count = 0
    skipped = 0
    failed = 0
    for skill in skills:
        # Skip API call if content hash unchanged since last enrichment
        if (skill.content_hash and skill.content_hash == skill.enriched_content_hash
                and skill.enriched_at and skill.ai_summary):
            skill.status = SkillStatus.ENRICHED.value
            from backend.evaluate import compute_final_score
            skill.score_final = compute_final_score(skill)
            session.add(skill)
            skipped += 1
            continue

        print(f"  Enriching: {skill.name} ({skill.repo_fullname})", file=sys.stderr)
        success = enrich_skill(skill)

        if success:
            skill.status = SkillStatus.ENRICHED.value
            skill.enriched_at = datetime.now(timezone.utc).isoformat()
            skill.skill_md_changed = False
            skill.enriched_content_hash = skill.content_hash

            from backend.evaluate import compute_final_score
            skill.score_final = compute_final_score(skill)
            count += 1
        else:
            failed += 1

        session.add(skill)

        # Commit in batches
        if (count + failed) % 10 == 0:
            session.commit()

    print(f"  Done: {count} enriched, {skipped} skipped (unchanged), {failed} failed", file=sys.stderr)
    session.commit()
    session.close()
    return count


def main():
    parser = argparse.ArgumentParser(description="AI-enrich evaluated skills")
    parser.add_argument("--limit", type=int, default=0, help="Max skills to enrich (0=all)")
    args = parser.parse_args()

    init_db()
    print("Enriching skills with AI...", file=sys.stderr)
    count = enrich_all(limit=args.limit)
    print(f"Enriched {count} skills", file=sys.stderr)


if __name__ == "__main__":
    main()
