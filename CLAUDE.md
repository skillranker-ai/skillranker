# CLAUDE.md

## Project: SkillRanker

Automated platform that discovers, scores, and ranks Claude Code Agent Skills from all of GitHub.

**Live site:** https://skillranker-ai.github.io/skillranker/
**Repo:** https://github.com/skillranker-ai/skillranker

## Architecture

4-layer pipeline: Discovery -> Evaluation -> AI Enrichment -> Static Site

### Backend (`backend/`)

| File | Purpose |
|------|---------|
| `config.py` | Settings, env vars, scoring weights, 15 domains |
| `models.py` | SQLModel DB models (Skill, DiscoveryRun) + Pydantic export schemas (SkillCard, DomainRanking, SiteCatalog) |
| `db.py` | SQLite (dev, `data/skillranker.db`) / Postgres (prod via `DATABASE_URL`) |
| `discover.py` | 4 GitHub search strategies + 6 awesome-lists, content validation, tree/metadata caching |
| `evaluate.py` | 5 hard metrics scoring (maintenance, docs, completeness, adoption, structure) |
| `enrich.py` | Claude Sonnet enrichment (summary, domains, tags, strengths/weaknesses, soft scores) |
| `export.py` | Generate `skills.json` (domain rankings, top overall, recently added, fastest growing) |
| `pipeline.py` | Full pipeline orchestrator with skip/limit flags |

### Discovery strategies

1. **Code Search `.claude/skills/`** — standard Claude Code skill location
2. **Code Search standalone** — SKILL.md with Claude frontmatter (`name:` + `description:`)
3. **Topic Search** — repos tagged `claude-code-skill`, `agent-skills`, etc.
4. **Repo Name Search** — repos with "claude" + "skill" in name
5. **Awesome-lists** — 6 curated lists parsed via Tree API

### Site (`site/`)

Astro static site with dark theme. Reads `site/public/skills.json` at build time.

- `src/pages/index.astro` — Homepage with domain rankings
- `src/pages/about.astro` — Scoring methodology
- `src/components/SkillCard.astro` — Skill display card
- `src/layouts/Base.astro` — Dark theme layout

### CI/CD (`.github/workflows/pipeline.yml`)

Daily cron at 6 AM UTC. Secrets: `GH_PAT`, `ANTHROPIC_API_KEY`.
Pipeline: discover (500/run) -> evaluate -> enrich (50/run) -> export -> build -> deploy to GitHub Pages.

## Commands

```bash
# Full pipeline
python -m backend.pipeline

# With limits (as in CI)
python -m backend.pipeline --discover-limit 500 --enrich-limit 50 --output site/public/skills.json

# Step by step
python -m backend.discover --source awesome
python -m backend.evaluate
python -m backend.enrich --limit 20
python -m backend.export

# Build site
cd site && npm install && npm run build
```

## Env vars

- `GITHUB_TOKEN` — GitHub PAT (required, 5000 req/h vs 60)
- `ANTHROPIC_API_KEY` — Claude API for enrichment
- `DATABASE_URL` — PostgreSQL URL (defaults to SQLite at `data/skillranker.db`)

## Data storage

- DB: `data/skillranker.db` (SQLite, auto-created)
- Export: `site/public/skills.json`
- Built site: `site/dist/`

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

## Domains (15)

coding, code-review, debugging, architecture, security, data-ml, documentation, research, prompt-engineering, agent-orchestration, devops, testing, creative, office-productivity, general
