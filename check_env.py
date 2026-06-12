"""Environment check for the Resume Maker app.

Verifies the three runtime dependencies before you build/run anything:
  1. Ollama is reachable and the configured model is pulled.
  2. pdflatex (MiKTeX) is on PATH.
  3. Python packages from requirements.txt import cleanly.

Run:  python check_env.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"{GREEN}[ OK ]{RESET} {msg}")


def fail(msg: str) -> None:
    print(f"{RED}[FAIL]{RESET} {msg}")


def warn(msg: str) -> None:
    print(f"{YELLOW}[WARN]{RESET} {msg}")


def check_packages() -> bool:
    missing = []
    for pkg in ("fastapi", "uvicorn", "jinja2", "yaml", "httpx", "pydantic"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        fail(f"Missing Python packages: {', '.join(missing)}. "
             f"Run: pip install -r requirements.txt")
        return False
    ok("Python packages installed.")
    return True


def check_pdflatex() -> bool:
    from app.config import PDFLATEX_BINARY

    path = shutil.which(PDFLATEX_BINARY)
    if not path:
        fail(f"'{PDFLATEX_BINARY}' not found on PATH. Install MiKTeX "
             f"(https://miktex.org/download), then reopen your terminal.")
        return False
    try:
        out = subprocess.run(
            [PDFLATEX_BINARY, "--version"],
            capture_output=True, text=True, timeout=20,
        )
        first_line = (out.stdout or out.stderr).splitlines()[0] if out.stdout or out.stderr else ""
        ok(f"pdflatex found: {path}  ({first_line})")
        return True
    except Exception as exc:  # noqa: BLE001
        fail(f"pdflatex found but failed to run: {exc}")
        return False


def check_ollama() -> bool:
    import httpx

    from app.config import OLLAMA_BASE_URL, OLLAMA_MODEL

    try:
        resp = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        fail(f"Ollama not reachable at {OLLAMA_BASE_URL} ({exc}). "
             f"Start it with 'ollama serve' (or the Ollama app).")
        return False

    models = [m.get("name", "") for m in resp.json().get("models", [])]
    # Match 'llama3.1' against 'Llama3.1:latest' etc. (case-insensitive, tag-agnostic).
    target = OLLAMA_MODEL.lower()
    if any(name.lower() == target or name.lower().startswith(target + ":") for name in models):
        ok(f"Ollama reachable; model '{OLLAMA_MODEL}' is available.")
        return True

    warn(f"Ollama reachable but model '{OLLAMA_MODEL}' not found. "
         f"Installed: {models or '(none)'}. Run: ollama pull {OLLAMA_MODEL}")
    return False


def main() -> int:
    print("Resume Maker — environment check\n")
    results = {
        "packages": check_packages(),
        "pdflatex": check_pdflatex(),
        "ollama": check_ollama(),
    }
    print()
    if all(results.values()):
        ok("All checks passed. You're ready to go.")
        return 0
    fail("Some checks failed — see messages above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
