"""
Export layer — generates skills.json for the static site.

Usage:
    python -m backend.export
    python -m backend.export --output site/public/skills.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import select

from backend.config import DOMAINS, EXPORT_DIR
from backend.db import get_session, init_db
from backend.models import DomainRanking, SiteCatalog, Skill, SkillCard, SkillStatus


def skill_to_card(skill: Skill) -> SkillCard:
    return SkillCard(
        id=skill.id or 0,
        name=skill.name,
        slug=skill.slug,
        repo_url=skill.repo_url,
        repo_fullname=skill.repo_fullname,
        stars=skill.stars,
        forks=skill.forks,
        license=skill.license,
        domains=skill.domains,
        tags=skill.tags,
        score_final=round(skill.score_final, 1),
        score_maintenance=round(skill.score_maintenance, 1),
        score_documentation=round(skill.score_documentation, 1),
        score_completeness=round(skill.score_completeness, 1),
        score_adoption=round(skill.score_adoption, 1),
        score_structure=round(skill.score_structure, 1),
        score_ai_quality=round(skill.score_ai_quality, 1),
        score_ai_usefulness=round(skill.score_ai_usefulness, 1),
        score_ai_novelty=round(skill.score_ai_novelty, 1),
        ai_summary=skill.ai_summary,
        ai_strengths=skill.ai_strengths,
        ai_weaknesses=skill.ai_weaknesses,
        ai_use_cases=skill.ai_use_cases,
        last_commit=skill.last_commit,
        latest_release=skill.latest_release,
        has_skill_md=skill.has_skill_md,
        has_references=skill.has_references,
        has_scripts=skill.has_scripts,
        has_examples=skill.has_examples,
        status=skill.status,
    )


def build_catalog() -> SiteCatalog:
    session = get_session()

    # Get all publishable skills (enriched or evaluated with sufficient score)
    skills = session.exec(
        select(Skill)
        .where(Skill.status.in_([
            SkillStatus.ENRICHED.value,
            SkillStatus.EVALUATED.value,
            SkillStatus.PUBLISHED.value,
        ]))
        .order_by(Skill.score_final.desc())
    ).all()

    cards = [skill_to_card(s) for s in skills]
    now = datetime.now(timezone.utc).isoformat()

    # Build domain rankings
    domain_rankings = []
    for domain in DOMAINS:
        domain_cards = [c for c in cards if domain in c.domains]
        domain_cards.sort(key=lambda c: -c.score_final)
        if domain_cards:
            domain_rankings.append(DomainRanking(
                domain=domain,
                skills=domain_cards[:50],  # top 50 per domain
                total=len(domain_cards),
                updated_at=now,
            ))

    # Skills without a matched domain go to "general"
    assigned = {c.slug for dr in domain_rankings for c in dr.skills}
    unassigned = [c for c in cards if c.slug not in assigned]
    if unassigned:
        general = next((dr for dr in domain_rankings if dr.domain == "general"), None)
        if general:
            existing_slugs = {c.slug for c in general.skills}
            for c in unassigned:
                if c.slug not in existing_slugs:
                    general.skills.append(c)
            general.total = len(general.skills)
            general.skills.sort(key=lambda c: -c.score_final)
        else:
            domain_rankings.append(DomainRanking(
                domain="general",
                skills=sorted(unassigned, key=lambda c: -c.score_final)[:50],
                total=len(unassigned),
                updated_at=now,
            ))

    # Sort domains by top score
    domain_rankings.sort(
        key=lambda dr: -dr.skills[0].score_final if dr.skills else 0
    )

    # Top overall
    top_overall = sorted(cards, key=lambda c: -c.score_final)[:20]

    # Recently added (by discovered_at proxy — use id as fallback)
    recently_added = sorted(cards, key=lambda c: -c.id)[:10]

    # Fastest growing (by stars, simple heuristic)
    fastest_growing = sorted(cards, key=lambda c: -c.stars)[:10]

    catalog = SiteCatalog(
        generated_at=now,
        total_skills=len(cards),
        domains=domain_rankings,
        top_overall=top_overall,
        recently_added=recently_added,
        fastest_growing=fastest_growing,
    )

    session.close()
    return catalog


def main():
    parser = argparse.ArgumentParser(description="Export skills catalog to JSON")
    parser.add_argument(
        "--output",
        type=str,
        default=str(EXPORT_DIR / "skills.json"),
        help="Output file path",
    )
    args = parser.parse_args()

    init_db()
    print("Building catalog...", file=sys.stderr)
    catalog = build_catalog()
    print(f"  {catalog.total_skills} skills, {len(catalog.domains)} domains", file=sys.stderr)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        catalog.model_dump_json(indent=2),
        encoding="utf-8",
    )
    print(f"Written to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
