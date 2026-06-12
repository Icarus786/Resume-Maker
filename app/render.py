"""Render resume / cover letter data into PDFs via Jinja2 + LaTeX (pdflatex).

Layout lives entirely in the .tex templates under `templates/`. This module
only fills placeholders and shells out to `pdflatex`. It never decides what
content goes where — that's the template's job — so the layout can't drift
based on LLM output.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import jinja2

from app.config import OUTPUT_DIR, PDFLATEX_BINARY, TEMPLATES_DIR, ensure_dirs

# --- Jinja2 environment with LaTeX-safe delimiters --------------------------
# Default Jinja2 delimiters ({{ }}, {% %}, {# #}) collide with LaTeX's heavy
# use of curly braces. Use << >> and <% %> instead, and disable autoescaping
# (we do explicit LaTeX escaping ourselves).
_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
    block_start_string="<%",
    block_end_string="%>",
    variable_start_string="<<",
    variable_end_string=">>",
    comment_start_string="<#",
    comment_end_string="#>",
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
)


# --- LaTeX special-character escaping ----------------------------------------
_LATEX_SPECIAL_CHARS = {
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "\\": r"\textbackslash{}",
}
_LATEX_ESCAPE_RE = re.compile("|".join(re.escape(c) for c in _LATEX_SPECIAL_CHARS))


def _escape_latex(value):
    """Escape LaTeX special characters in strings; recurse into containers."""
    if isinstance(value, str):
        return _LATEX_ESCAPE_RE.sub(lambda m: _LATEX_SPECIAL_CHARS[m.group()], value)
    if isinstance(value, list):
        return [_escape_latex(v) for v in value]
    if isinstance(value, dict):
        return {k: _escape_latex(v) for k, v in value.items()}
    return value


class LatexCompileError(RuntimeError):
    """Raised when pdflatex fails to produce a PDF."""


# Resumes longer than this are recompiled in compact mode (tighter spacing).
MAX_RESUME_PAGES = 2

_PAGE_COUNT_RE = re.compile(r"\((\d+) pages?,")


def _page_count(log_path: Path) -> int | None:
    """Parse the page count pdflatex reports in its log, if present.

    pdflatex hard-wraps its log at ~79 columns, which can split the
    "Output written on ... (N pages, ...)" line across two lines (often
    mid-path), so strip newlines before matching.
    """
    if not log_path.exists():
        return None
    log_text = log_path.read_text(encoding="utf-8", errors="replace").replace("\n", "")
    match = _PAGE_COUNT_RE.search(log_text)
    return int(match.group(1)) if match else None


def _compile_tex(tex_source: str, job_name: str, out_dir: Path) -> Path:
    """Write `tex_source` to `out_dir/job_name.tex` and compile it to PDF.

    Runs pdflatex twice (for stable cross-references / hyperlinks), in
    nonstopmode so a single bad character doesn't hang the process. Raises
    LatexCompileError with the tail of the log on failure.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    tex_path = out_dir / f"{job_name}.tex"
    tex_path.write_text(tex_source, encoding="utf-8")

    if shutil.which(PDFLATEX_BINARY) is None:
        raise LatexCompileError(
            f"'{PDFLATEX_BINARY}' not found on PATH. Install MiKTeX "
            f"(https://miktex.org/download) and reopen your terminal."
        )

    pdf_path = out_dir / f"{job_name}.pdf"
    log_path = out_dir / f"{job_name}.log"

    for _ in range(2):
        result = subprocess.run(
            [
                PDFLATEX_BINARY,
                "-interaction=nonstopmode",
                "-halt-on-error",
                f"-output-directory={out_dir}",
                str(tex_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0 or not pdf_path.exists():
            log_tail = ""
            if log_path.exists():
                log_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                log_tail = "\n".join(log_lines[-40:])
            raise LatexCompileError(
                f"pdflatex failed for {tex_path.name} (exit {result.returncode}).\n"
                f"--- log tail ---\n{log_tail}\n"
                f"--- stdout tail ---\n{result.stdout[-2000:]}"
            )

    return pdf_path


def render_resume(resume_dict: dict, job_name: str = "resume", out_dir: Path | None = None) -> Path:
    """Render a resume dict into a PDF and return its path.

    `resume_dict` should match the shape of `app.models.Resume` (e.g. from
    `resume_to_dict()`), optionally with a tailored `title_line` / bullets.

    If the rendered resume exceeds `MAX_RESUME_PAGES`, it is automatically
    recompiled with tighter ("compact") spacing to try to fit within the
    limit. The resume content itself is never altered.
    """
    ensure_dirs()
    out_dir = out_dir or OUTPUT_DIR

    template = _env.get_template("resume_template.tex")
    safe_data = _escape_latex(resume_dict)

    tex_source = template.render(**safe_data, compact=False)
    pdf_path = _compile_tex(tex_source, job_name, out_dir)

    pages = _page_count(out_dir / f"{job_name}.log")
    if pages is not None and pages > MAX_RESUME_PAGES:
        tex_source = template.render(**safe_data, compact=True)
        pdf_path = _compile_tex(tex_source, job_name, out_dir)

    return pdf_path


def render_cover_letter(context: dict, job_name: str = "cover_letter", out_dir: Path | None = None) -> Path:
    """Render a cover letter context dict into a PDF and return its path.

    `context` is expected to provide: contact, date, company, role, and
    `paragraphs` (list[str]) with the body text.
    """
    ensure_dirs()
    out_dir = out_dir or OUTPUT_DIR

    template = _env.get_template("cover_letter_template.tex")
    safe_data = _escape_latex(context)
    tex_source = template.render(**safe_data)

    return _compile_tex(tex_source, job_name, out_dir)


if __name__ == "__main__":
    # Quick manual check: python -m app.render
    import sys

    from app.config import MASTER_RESUME_PATH
    from app.models import load_resume, resume_to_dict

    try:
        resume = load_resume(MASTER_RESUME_PATH)
    except (ValueError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    try:
        pdf_path = render_resume(resume_to_dict(resume), job_name="resume")
    except LatexCompileError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    print(f"Resume PDF written to: {pdf_path}")
