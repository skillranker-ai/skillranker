"""Configuration for the SkillRanker pipeline."""

import os
from pathlib import Path

# --- Paths ---
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
EXPORT_DIR = PROJECT_ROOT / "site" / "public"

# --- GitHub API ---
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_API = "https://api.github.com"
GITHUB_AWESOME_LISTS = [
    "hesreallyhim/awesome-claude-code",
    "ComposioHQ/awesome-claude-skills",
    "sickn33/antigravity-awesome-skills",
    "numman-ali/openskills",
    "alirezarezvani/claude-skills",
    "daymade/claude-code-skills",
]

# --- LLM ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_MODEL = "claude-sonnet-4-20250514"
LLM_MAX_TOKENS = 2048

# --- Database ---
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{DATA_DIR / 'skillranker.db'}",
)

# --- Scoring weights ---
SCORE_WEIGHTS = {
    # Hard metrics (70%)
    "maintenance": 0.20,
    "documentation": 0.15,
    "completeness": 0.15,
    "adoption": 0.10,
    "structure": 0.10,
    # Soft metrics from AI (30%)
    "ai_quality": 0.10,
    "ai_usefulness": 0.10,
    "ai_novelty": 0.10,
}

# --- Categories ---
DOMAINS = [
    "coding",
    "code-review",
    "debugging",
    "architecture",
    "security",
    "data-ml",
    "documentation",
    "research",
    "prompt-engineering",
    "agent-orchestration",
    "devops",
    "testing",
    "creative",
    "office-productivity",
    "general",
]
