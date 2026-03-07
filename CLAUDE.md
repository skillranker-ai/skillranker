# CLAUDE.md

## Project: SkillRanker

AI-powered ranking platform for Claude Code Agent Skills.

**Live site:** https://skillranker-ai.github.io/skillranker/
**Repo:** https://github.com/skillranker-ai/skillranker

## Architecture

4-layer pipeline: Discovery -> Evaluation -> AI Enrichment -> Static Site

### Backend (`backend/`)

| File | Purpose |
|------|---------|
| `config.py` | Settings, env vars, scoring weights, domains |
| `models.py` | SQLModel DB models + Pydantic export schemas |
| `db.py` | SQLite (dev) / Postgres (prod) engine |
| `discover.py` | GitHub API search + awesome-list parsing |
| `evaluate.py` | Hard metric scoring (maintenance, docs, completeness, adoption, structure) |
| `enrich.py` | Claude API enrichment (summary, categories, soft scores) |
| `export.py` | Generate `skills.json` for Astro site |
| `pipeline.py` | Full pipeline runner |

### Site (`site/`)

Astro static site. Reads `site/public/skills.json` at build time.

- `src/pages/index.astro` — Homepage with domain rankings
- `src/pages/about.astro` — Scoring methodology
- `src/components/SkillCard.astro` — Skill display card
- `src/layouts/Base.astro` — Dark theme layout

### CI/CD (`.github/workflows/pipeline.yml`)

Daily cron at 6 AM UTC: discover -> evaluate -> enrich -> export -> build -> deploy to GitHub Pages.

## Commands

```bash
# Full pipeline
python -m backend.pipeline

# Step by step
python -m backend.discover --source awesome
python -m backend.evaluate
python -m backend.enrich --limit 20
python -m backend.export

# Build site
cd site && npm install && npm run build
```

## Env vars

- `GITHUB_TOKEN` — GitHub PAT (recommended, 5000 req/h vs 60)
- `ANTHROPIC_API_KEY` — Claude API for enrichment
- `DATABASE_URL` — PostgreSQL URL (defaults to SQLite)

## Scoring

70% hard metrics + 30% AI:
- maintenance (20%): commits, releases, contributors
- documentation (15%): SKILL.md quality, README
- completeness (15%): references, scripts, examples
- adoption (10%): stars, forks (log-scaled)
- structure (10%): license, tests, CI, topics
- ai_quality (10%): clarity, coherence
- ai_usefulness (10%): practical value
- ai_novelty (10%): uniqueness
