"""
Deduplication layer — detects and removes duplicate skills.

Two-layer approach:
  1. Exact duplicates: same content_hash (identical SKILL.md)
  2. Near-duplicates: same near_hash (minor whitespace/formatting differences)

In both cases, the highest-scored version is kept, others are REJECTED.

Usage:
    python -m backend.dedup
"""

from __future__ import annotations

import sys
from collections import defaultdict

from sqlmodel import select

from backend.db import get_session, init_db
from backend.models import Skill, SkillStatus


def dedup_skills() -> int:
    """Mark duplicate skills as REJECTED. Returns count of rejected dupes.

    Keeps the version with the highest score_final (or most stars as tiebreak).
    Only deduplicates skills that haven't been rejected yet.
    """
    session = get_session()

    # Get all non-rejected skills that have a near_hash
    skills = session.exec(
        select(Skill).where(
            Skill.status != SkillStatus.REJECTED.value,
            Skill.near_hash != "",
        )
    ).all()

    # Group by near_hash
    groups: dict[str, list[Skill]] = defaultdict(list)
    for skill in skills:
        groups[skill.near_hash].append(skill)

    rejected = 0
    for near_hash, group in groups.items():
        if len(group) <= 1:
            continue

        # Sort: highest score_final first, then stars as tiebreak
        group.sort(key=lambda s: (-s.score_final, -s.stars, s.id or 0))
        keeper = group[0]

        for dupe in group[1:]:
            print(
                f"  Dedup: rejecting '{dupe.name}' ({dupe.repo_fullname}) "
                f"— duplicate of '{keeper.name}' ({keeper.repo_fullname})",
                file=sys.stderr,
            )
            dupe.status = SkillStatus.REJECTED.value
            session.add(dupe)
            rejected += 1

    if rejected:
        print(f"  Dedup: {rejected} duplicates rejected", file=sys.stderr)
    session.commit()
    session.close()
    return rejected


def main():
    init_db()
    print("Running deduplication...", file=sys.stderr)
    count = dedup_skills()
    print(f"Rejected {count} duplicates", file=sys.stderr)


if __name__ == "__main__":
    main()
