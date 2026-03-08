# SkillRanker

Automatyczna platforma do odkrywania, oceniania i rankingowania **Claude Code Agent Skills** z całego GitHuba.

**Live site:** https://skillranker-ai.github.io/skillranker/
**Repo:** https://github.com/skillranker-ai/skillranker

## Czym jest SkillRanker?

Claude Code pozwala rozszerzać możliwości agenta o własne **Skills** — pliki `SKILL.md` definiujące instrukcje, narzędzia i wzorce pracy. Na GitHubie istnieją tysiące takich plików, ale nie ma jednego miejsca, które zbiera je, porównuje i rankinguje.

**SkillRanker** to w pełni zautomatyzowany pipeline, który:

1. **Przeszukuje cały GitHub** w poszukiwaniu plików `SKILL.md` — zarówno w standardowej lokalizacji `.claude/skills/`, jak i w repozytoriach z awesome-list oraz tagged topics
2. **Ocenia każdy skill** obiektywnie na podstawie twardych metryk (aktywność repo, dokumentacja, struktura, popularność)
3. **Wzbogaca oceną AI** — Claude czyta treść każdego SKILL.md i ocenia jakość, użyteczność i nowatorskość
4. **Publikuje ranking** jako statyczną stronę na GitHub Pages, aktualizowaną codziennie

Wynik: **ranking najlepszych skills pogrupowany w 15 domen** (coding, security, devops, testing, architecture, itd.)

## Jak działa pipeline?

```
Discovery (GitHub API) ──> Evaluation (reguły) ──> AI Enrichment (Claude) ──> Export (JSON) ──> Site (Astro)
```

### 1. Discovery (`backend/discover.py`)

Przeszukuje GitHub czterema strategiami:

| Strategia | Co szuka | Jak |
|-----------|----------|-----|
| **Strategy 1** | `SKILL.md` w `.claude/skills/` | GitHub Code Search API |
| **Strategy 1b** | Standalone `SKILL.md` z frontmatter Claude | Code Search + walidacja treści |
| **Strategy 2** | Repozytoria z topicami `claude-code-skill`, `agent-skills` itp. | Repo Search + Tree API |
| **Strategy 3** | Repozytoria z "claude" + "skill" w nazwie | Repo Search + Tree API |
| **Awesome-lists** | 6 kuratorskich list z linkami do skill repos | Parsowanie README + Tree API |

**Awesome-lists źródłowe:**
- `hesreallyhim/awesome-claude-code`
- `ComposioHQ/awesome-claude-skills`
- `sickn33/antigravity-awesome-skills`
- `numman-ali/openskills`
- `alirezarezvani/claude-skills`
- `daymade/claude-code-skills`

Każdy odkryty skill jest walidowany — sprawdzamy, czy to faktycznie Claude Code skill (obecność `name:`, `description:` w frontmatter, lub lokalizacja w `.claude/skills/`).

### 2. Evaluation (`backend/evaluate.py`)

5 twardych metryk, każda 0–100:

| Metryka | Waga | Co mierzy |
|---------|------|-----------|
| **Maintenance** | 20% | Świeżość commitów, liczba releases, kontrybutorzy |
| **Documentation** | 15% | Jakość SKILL.md (długość, sekcje, przykłady kodu), README |
| **Completeness** | 15% | Obecność: references/, scripts/, examples/, templates/ |
| **Adoption** | 10% | Stars, forks, watchers (skala logarytmiczna) |
| **Structure** | 10% | Licencja, testy, CI/CD, topics |

### 3. AI Enrichment (`backend/enrich.py`)

Claude Sonnet czyta treść SKILL.md i generuje:

- **Podsumowanie** — 2-3 zdania co robi skill
- **Domeny** — przypisanie do 1-3 z 15 kategorii
- **Tagi** — 3-5 słów kluczowych
- **Mocne/słabe strony** — lista bullet points
- **Przypadki użycia** — kiedy warto użyć
- **3 soft score'y** (po 10% każdy): jakość, użyteczność, nowatorskość

### 4. Export (`backend/export.py`)

Generuje `skills.json` z pełnym katalogiem:
- Rankingi per domena (top skills w każdej z 15 kategorii)
- Top Overall (najlepsze niezależnie od domeny)
- Recently Added
- Fastest Growing

### 5. Site (`site/`)

Statyczna strona Astro z dark theme, czytająca `skills.json` w build time. Deployowana na GitHub Pages.

## Gdzie zapisuje dane?

| Co | Gdzie | Format |
|----|-------|--------|
| **Baza danych** | `data/skillranker.db` | SQLite (dev) / PostgreSQL (prod via `DATABASE_URL`) |
| **Eksport do strony** | `site/public/skills.json` | JSON (Pydantic schema) |
| **Zbudowana strona** | `site/dist/` | Static HTML/CSS/JS |

Baza SQLite tworzy się automatycznie przy pierwszym uruchomieniu. Zawiera dwie tabele:
- `skills` — wszystkie odkryte skille z metrykami, ocenami i treścią AI
- `discoveryruns` — audit trail każdego uruchomienia discovery

## Wymagania

### Zmienne środowiskowe

| Zmienna | Wymagana? | Opis |
|---------|-----------|------|
| `GITHUB_TOKEN` | **Tak** (bez tokena max 60 req/h) | GitHub Personal Access Token — potrzebny do przeszukiwania API (5000 req/h z tokenem) |
| `ANTHROPIC_API_KEY` | Tylko dla enrichment | Klucz API Claude — potrzebny do generowania podsumowań i ocen AI |
| `DATABASE_URL` | Nie (domyślnie SQLite) | URL do PostgreSQL (np. `postgresql://user:pass@host/db`) |

### Zależności Python

```bash
pip install -r requirements.txt
```

Główne: `sqlmodel`, `pydantic`, `anthropic`

### Zależności Node (dla strony)

```bash
cd site && npm install
```

Główne: `astro`

## Quick start

```bash
# 1. Zainstaluj zależności
pip install -r requirements.txt

# 2. Ustaw token GitHub (wymagany!)
export GITHUB_TOKEN="ghp_twój_token"

# 3. Pełny pipeline (bez AI enrichment)
python -m backend.pipeline --skip-enrich

# 4. Z AI enrichment (wymaga ANTHROPIC_API_KEY)
export ANTHROPIC_API_KEY="sk-ant-..."
python -m backend.pipeline --enrich-limit 20

# 5. Zbuduj stronę
cd site && npm install && npm run build
```

### Komendy krok po kroku

```bash
# Tylko discovery (z awesome-lists)
python -m backend.discover --source awesome

# Tylko discovery (pełny skan GitHub)
python -m backend.discover --source search

# Evaluation
python -m backend.evaluate

# AI Enrichment (limit 20 skills)
python -m backend.enrich --limit 20

# Export do JSON
python -m backend.export
```

### Flagi pipeline

```bash
python -m backend.pipeline \
  --discover-source all \      # all | search | awesome
  --discover-limit 500 \       # max skills do zapisania (0 = bez limitu)
  --skip-evaluate \             # pomiń evaluation
  --skip-enrich \               # pomiń AI enrichment
  --enrich-limit 50 \           # max skills do wzbogacenia AI
  --full-metadata \             # pobierz CI/tests/contributors/releases (5 extra API calls/repo)
  --output path/to/skills.json  # ścieżka wyjściowa (domyślnie site/public/skills.json)
```

## Deployment (CI/CD)

GitHub Actions (`.github/workflows/pipeline.yml`) uruchamia pipeline automatycznie:

| Trigger | Kiedy |
|---------|-------|
| **Cron** | Codziennie o 6:00 UTC |
| **Push to main** | Przy zmianach w `backend/`, `site/`, lub workflow |
| **Manual** | Ręcznie via workflow_dispatch |

Pipeline w CI: discover (500/run) → evaluate → enrich (50/run) → export → build Astro → deploy to GitHub Pages

### Wymagane sekrety w GitHub Actions

| Secret | Opis |
|--------|------|
| `GH_PAT` | GitHub Personal Access Token (mapowany na `GITHUB_TOKEN`) |
| `ANTHROPIC_API_KEY` | Klucz Claude API |

Ustaw w: Settings → Secrets and variables → Actions

### GitHub Pages

Włącz w: Settings → Pages → Source: **GitHub Actions**

## Scoring — jak działa ocena?

Każdy skill dostaje wynik **0–100**, będący ważoną sumą 8 metryk:

```
Final Score = 70% hard metrics + 30% AI metrics

Hard metrics:
  maintenance   × 0.20   (świeżość, releases, contributors)
  documentation × 0.15   (jakość SKILL.md, README)
  completeness  × 0.15   (references, scripts, examples)
  adoption      × 0.10   (stars, forks — log scale)
  structure     × 0.10   (license, tests, CI, topics)

AI metrics:
  ai_quality    × 0.10   (klarowność, spójność)
  ai_usefulness × 0.10   (praktyczna wartość)
  ai_novelty    × 0.10   (unikalność podejścia)
```

## Domeny (15 kategorii)

Skills są przypisywane do 1-3 domen przez AI:

`coding` · `code-review` · `debugging` · `architecture` · `security` · `data-ml` · `documentation` · `research` · `prompt-engineering` · `agent-orchestration` · `devops` · `testing` · `creative` · `office-productivity` · `general`

## Struktura projektu

```
skillranker/
├── backend/
│   ├── config.py          # Konfiguracja, wagi, domeny, env vars
│   ├── models.py          # SQLModel (DB) + Pydantic (export) schemas
│   ├── db.py              # SQLite (dev) / PostgreSQL (prod)
│   ├── discover.py        # 4 strategie discovery z GitHub API
│   ├── evaluate.py        # 5 hard metrics (0-100 każda)
│   ├── enrich.py          # Claude API — podsumowania, domeny, soft scores
│   ├── export.py          # Generuje skills.json dla strony
│   └── pipeline.py        # Orchestrator: discover → evaluate → enrich → export
├── site/
│   ├── src/
│   │   ├── pages/         # index.astro (ranking), about.astro (metodologia)
│   │   ├── components/    # SkillCard.astro
│   │   └── layouts/       # Base.astro (dark theme)
│   ├── public/
│   │   └── skills.json    # Generowany przez pipeline
│   └── astro.config.mjs   # GitHub Pages config
├── data/
│   └── skillranker.db     # SQLite database (auto-created)
├── .github/workflows/
│   └── pipeline.yml       # Daily cron + deploy to Pages
└── requirements.txt
```

## Rate limits i optymalizacje

- **GitHub API**: 5000 req/h z tokenem, 60 bez. Pipeline używa caching (metadata, tree, README per repo) żeby minimalizować wywołania
- **Discovery limit**: `--discover-limit 500` w CI — dodaje max 500 nowych skills na run. Baza rośnie inkrementalnie
- **Enrich limit**: `--enrich-limit 50` — AI wzbogaca max 50 skills na run (koszt API)
- **Tree API**: 1 wywołanie na repo zamiast N (sprawdza strukturę plików jednym zapytaniem)
- **Content validation**: Filtruje fałszywe wyniki (nie-Claude pliki SKILL.md) przed zapisem do bazy
