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
LLM_MAX_TOKENS = 4096

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
    "ai_quality": 0.06,       # code/instruction clarity and coherence
    "ai_usefulness": 0.08,    # practical value for real-world work
    "ai_novelty": 0.06,       # uniqueness, not a copy/rehash
    "ai_description": 0.05,   # quality of SKILL.md description itself
    "ai_reusability": 0.05,   # how portable/reusable across projects
}

# --- Categories ---
# Suggested domains — Claude can also create new ones during enrichment.
# After enrichment, export.py collects all actual domains from DB.
DOMAINS = [
    # Development
    "coding",
    "code-review",
    "debugging",
    "testing",
    "architecture",
    "frontend",
    "backend",
    # Operations
    "devops",
    "cloud-infrastructure",
    "automation",
    # Security
    "security",
    "pentesting",
    # Data & AI
    "data-science",
    "machine-learning",
    "scientific-computing",
    # Content & Communication
    "documentation",
    "technical-writing",
    "marketing-seo",
    "communication",
    # Business & Management
    "project-management",
    "product-management",
    "business-strategy",
    # Agent & AI tooling
    "prompt-engineering",
    "agent-orchestration",
    "mcp-integration",
    # Research & Learning
    "research",
    "education",
    # Creative
    "creative",
    "design",
    # Other
    "office-productivity",
    "finance",
    "general",
]
