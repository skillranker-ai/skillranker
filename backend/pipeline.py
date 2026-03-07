"""
Full pipeline runner — discovery -> evaluation -> enrichment -> export.

Usage:
    python -m backend.pipeline              # full pipeline
    python -m backend.pipeline --skip-discover
    python -m backend.pipeline --skip-enrich
    python -m backend.pipeline --enrich-limit 20
"""

from __future__ import annotations

import argparse
import sys

from backend.db import init_db


def main():
    parser = argparse.ArgumentParser(description="Run the SkillRanker pipeline")
    parser.add_argument("--skip-discover", action="store_true")
    parser.add_argument("--skip-evaluate", action="store_true")
    parser.add_argument("--skip-enrich", action="store_true")
    parser.add_argument("--skip-export", action="store_true")
    parser.add_argument("--enrich-limit", type=int, default=0)
    parser.add_argument("--discover-source", choices=["all", "search", "awesome"], default="all")
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    init_db()

    # 1. Discovery
    if not args.skip_discover:
        print("=" * 60, file=sys.stderr)
        print("STEP 1: Discovery", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        from backend.discover import discover_from_awesome, discover_from_search
        from backend.discover import persist_discoveries
        from backend.models import DiscoveryRun

        run = DiscoveryRun(source=args.discover_source)
        discoveries = []

        if args.discover_source in ("all", "search"):
            discoveries.extend(discover_from_search(run))
        if args.discover_source in ("all", "awesome"):
            discoveries.extend(discover_from_awesome(run))

        total, new = persist_discoveries(discoveries, run)
        print(f"  Result: {total} found, {new} new\n", file=sys.stderr)

    # 2. Evaluation
    if not args.skip_evaluate:
        print("=" * 60, file=sys.stderr)
        print("STEP 2: Evaluation", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        from backend.evaluate import evaluate_all

        count = evaluate_all()
        print(f"  Result: {count} evaluated\n", file=sys.stderr)

    # 3. Enrichment
    if not args.skip_enrich:
        print("=" * 60, file=sys.stderr)
        print("STEP 3: AI Enrichment", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        from backend.enrich import enrich_all

        count = enrich_all(limit=args.enrich_limit)
        print(f"  Result: {count} enriched\n", file=sys.stderr)

    # 4. Export
    if not args.skip_export:
        print("=" * 60, file=sys.stderr)
        print("STEP 4: Export", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        from backend.export import build_catalog
        from pathlib import Path
        from backend.config import EXPORT_DIR

        catalog = build_catalog()
        output = Path(args.output) if args.output else EXPORT_DIR / "skills.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(catalog.model_dump_json(indent=2), encoding="utf-8")
        print(f"  Result: {catalog.total_skills} skills exported to {output}\n", file=sys.stderr)

    print("Pipeline complete.", file=sys.stderr)


if __name__ == "__main__":
    main()
