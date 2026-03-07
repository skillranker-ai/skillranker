"""
AI enrichment layer — uses Claude to generate summaries, categories,
strengths/weaknesses, and soft quality scores.

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
from backend.db import get_session, init_db
from backend.models import Skill, SkillStatus


ENRICHMENT_PROMPT = """\
You are an expert evaluator of Claude Code Agent Skills.

Analyze this skill and return a JSON object with exactly these fields:

{{
  "domains": ["<primary domain>", "<optional secondary>"],
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "summary": "<2-3 sentence summary of what this skill does and when to use it>",
  "strengths": ["strength 1", "strength 2", "strength 3"],
  "weaknesses": ["weakness 1", "weakness 2"],
  "use_cases": ["use case 1", "use case 2", "use case 3"],
  "score_quality": <0-100 integer: code/doc quality, clarity, structure>,
  "score_usefulness": <0-100 integer: practical value for developers>,
  "score_novelty": <0-100 integer: uniqueness, not a copy/rehash>
}}

Valid domains (pick 1-2): {domains}

SKILL NAME: {name}
REPO: {repo}
STARS: {stars}
LICENSE: {license}

SKILL.md content (first 3000 chars):
{skill_md}

README (first 1000 chars):
{readme}

Return ONLY the JSON object, no markdown fences, no explanation.
"""


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
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # Handle potential markdown fences
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  JSON parse error: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  Claude API error: {e}", file=sys.stderr)
        return None


def enrich_skill(skill: Skill) -> bool:
    """Enrich a single skill with AI-generated content. Returns True on success."""
    prompt = ENRICHMENT_PROMPT.format(
        domains=", ".join(DOMAINS),
        name=skill.name,
        repo=skill.repo_fullname,
        stars=skill.stars,
        license=skill.license,
        skill_md=skill.skill_md_raw[:3000],
        readme=skill.readme_raw[:1000],
    )

    result = _call_claude(prompt)
    if not result:
        return False

    skill.domains = result.get("domains", ["general"])
    skill.tags = result.get("tags", [])
    skill.ai_summary = result.get("summary", "")
    skill.ai_strengths = result.get("strengths", [])
    skill.ai_weaknesses = result.get("weaknesses", [])
    skill.ai_use_cases = result.get("use_cases", [])
    skill.score_ai_quality = float(result.get("score_quality", 0))
    skill.score_ai_usefulness = float(result.get("score_usefulness", 0))
    skill.score_ai_novelty = float(result.get("score_novelty", 0))

    return True


def enrich_all(limit: int = 0) -> int:
    """Enrich evaluated skills. Returns count enriched."""
    session = get_session()
    query = select(Skill).where(Skill.status == SkillStatus.EVALUATED.value)
    if limit > 0:
        query = query.limit(limit)
    skills = session.exec(query).all()

    count = 0
    for skill in skills:
        print(f"  Enriching: {skill.name} ({skill.repo_fullname})", file=sys.stderr)
        success = enrich_skill(skill)

        if success:
            skill.status = SkillStatus.ENRICHED.value
            skill.enriched_at = datetime.now(timezone.utc).isoformat()

            # Recompute final score with AI scores
            from backend.evaluate import compute_final_score
            skill.score_final = compute_final_score(skill)

            count += 1
        else:
            # Still update status to avoid re-processing on next run
            # but keep as evaluated — can retry later
            pass

        session.add(skill)

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
