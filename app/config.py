"""Central configuration and shared paths for the Resume Maker app.

All paths are resolved relative to the project root so the app works no matter
where it is launched from.
"""
from __future__ import annotations

import os
from pathlib import Path

# Project root = parent of the `app/` package directory.
ROOT_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT_DIR / "data"
TEMPLATES_DIR = ROOT_DIR / "templates"
OUTPUT_DIR = ROOT_DIR / "output"
STATIC_DIR = ROOT_DIR / "app" / "static"

MASTER_RESUME_PATH = DATA_DIR / "master_resume.yaml"

# Persisted keyword -> category routing table used by `tailor_resume` to fix
# recurring miscategorizations of JD keywords. See
# data/skill_category_map.yaml for format and how to add corrections.
SKILL_CATEGORY_MAP_PATH = DATA_DIR / "skill_category_map.yaml"

# --- Ollama settings -------------------------------------------------------
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
# Note: Ollama model names are case-sensitive when calling. Your installed tag
# is 'Llama3.1:latest'. Override via the OLLAMA_MODEL env var if yours differs.
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "Llama3.1:latest")
# Low temperature keeps tailoring deterministic and reduces hallucination.
OLLAMA_TEMPERATURE = float(os.environ.get("OLLAMA_TEMPERATURE", "0.2"))
# Generous timeout: local generation on CPU can be slow.
OLLAMA_TIMEOUT_SECONDS = float(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "300"))

# --- LaTeX settings --------------------------------------------------------
# Override if pdflatex is not on PATH, e.g. a full MiKTeX install path.
PDFLATEX_BINARY = os.environ.get("PDFLATEX_BINARY", "pdflatex")


def ensure_dirs() -> None:
    """Create the runtime directories that must exist."""
    for d in (DATA_DIR, TEMPLATES_DIR, OUTPUT_DIR, STATIC_DIR):
        d.mkdir(parents=True, exist_ok=True)
