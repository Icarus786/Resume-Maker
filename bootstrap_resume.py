"""One-time helper: convert your existing resume text into master_resume.yaml.

This is EXTRACTION ONLY - the LLM copies your existing content into the
required structure without embellishment. You should review and correct the
output by hand afterwards (especially: skill groupings, title_line, and any
fields the model left as null/empty).

Usage:
    python bootstrap_resume.py path/to/resume.txt
    python bootstrap_resume.py path/to/resume.txt --out data/master_resume.yaml

If no file path is given, reads resume text from stdin (paste, then Ctrl-Z
then Enter on Windows to end input).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from app.config import MASTER_RESUME_PATH, ensure_dirs
from app.llm import OllamaError, bootstrap_resume_from_text
from app.models import Resume, ValidationError


def _read_input(path: str | None) -> str:
    if path:
        p = Path(path)
        if not p.exists():
            print(f"ERROR: file not found: {p}", file=sys.stderr)
            sys.exit(1)
        return p.read_text(encoding="utf-8")

    print("Paste your resume text, then press Ctrl-Z and Enter (Windows) "
          "or Ctrl-D (Unix) to finish:\n", file=sys.stderr)
    return sys.stdin.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", help="Path to a text file containing your resume content")
    parser.add_argument(
        "--out", default=str(MASTER_RESUME_PATH),
        help=f"Output YAML path (default: {MASTER_RESUME_PATH})",
    )
    args = parser.parse_args()

    resume_text = _read_input(args.input)
    if not resume_text.strip():
        print("ERROR: no resume text provided.", file=sys.stderr)
        return 1

    print("Extracting resume structure with local LLM... this can take a minute.", file=sys.stderr)
    try:
        extracted = bootstrap_resume_from_text(resume_text)
    except (OllamaError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # Validate against the schema, filling in any required defaults so the
    # output is always loadable even if the model left gaps.
    extracted.setdefault("contact", {})
    extracted["contact"].setdefault("name", "")
    extracted["contact"].setdefault("email", "")

    # `experience[].start`/`end` are required strings, but the model may
    # return null for an ongoing role (e.g. "Present" in the source text was
    # implied by an empty end date). Default missing end dates to "Present".
    for job in extracted.get("experience", []) or []:
        if not job.get("start"):
            job["start"] = ""
        if not job.get("end"):
            job["end"] = "Present"

    try:
        resume = Resume.model_validate(extracted)
    except ValidationError as exc:
        print(f"ERROR: extracted data failed validation:\n{exc}", file=sys.stderr)
        print("\nRaw extracted data (for debugging):", file=sys.stderr)
        print(extracted, file=sys.stderr)
        return 1

    out_path = Path(args.out)
    ensure_dirs()

    if out_path.exists():
        backup = out_path.with_suffix(out_path.suffix + ".bak")
        out_path.replace(backup)
        print(f"Existing file backed up to: {backup}", file=sys.stderr)

    out_path.write_text(
        "# Bootstrapped from your resume text - REVIEW AND CORRECT BY HAND.\n"
        "# Especially check: title_line, skill groupings, and any null/empty fields.\n"
        + yaml.dump(resume.model_dump(), sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )

    print(f"\nWrote {out_path}")
    print("Next steps:")
    print(f"  1. Open {out_path} and review every section against your real resume.")
    print("  2. Run: python -m app.models   (to validate it loads correctly)")
    print("  3. Run: python -m app.render   (to render a PDF and check the layout)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
