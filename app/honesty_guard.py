"""Honesty guard: flag tailored content that introduces facts not in the master resume.

This is a deterministic, non-LLM backstop against fabrication. It checks that
every number (percentages, dollar amounts, counts, years) appearing in a
tailored bullet also appears somewhere in the corresponding original text (or
elsewhere in the master resume, for numbers that may have moved between
bullets during reordering/rewording).

This is intentionally conservative and approximate: it cannot verify that a
*tool name* wasn't swapped for another, only that *numeric claims* aren't
invented. It is a safety net, not a substitute for the user reviewing the diff.
"""
from __future__ import annotations

import re

# Matches numbers with optional %, $, or x suffix/prefix: 50%, $100, 5x, 2+, 99.9%
_NUMBER_RE = re.compile(r"\$?\d[\d,]*\.?\d*\s*[%x+]?", re.IGNORECASE)


def _extract_numbers(text: str) -> set[str]:
    """Extract normalized numeric tokens from text (digits + %, $, x, + markers)."""
    found = set()
    for match in _NUMBER_RE.finditer(text):
        token = match.group().strip()
        # Normalize whitespace between number and suffix, e.g. "50 %" -> "50%"
        token = re.sub(r"\s+", "", token)
        if any(c.isdigit() for c in token):
            found.add(token)
    return found


def check_resume(master: dict, tailored: dict) -> list[dict]:
    """Compare tailored vs. master resume and flag suspicious new numbers.

    Returns a list of warning dicts:
        {"location": "summary", "tailored_text": str,
         "suspicious_numbers": [str, ...]}

    A warning is raised when the tailored summary contains a numeric token \
that does not appear ANYWHERE in the master resume's text (skills, summary, \
experience/project bullets) - i.e. a number that looks invented rather than \
moved/reworded. `summary` is the only field the LLM may rewrite in free text;
`skills`/`experience`/`projects` are either reordered-only or untouched.
    """
    # Collect every numeric token that appears anywhere in the master resume.
    master_numbers: set[str] = set()
    master_numbers |= _extract_numbers(master.get("summary") or "")
    master_numbers |= _extract_numbers(master.get("title_line") or "")
    for group in master.get("skills", []) or []:
        for kw in group.get("keywords", []) or []:
            master_numbers |= _extract_numbers(kw)
    for job in master.get("experience", []) or []:
        for bullet in job.get("bullets", []) or []:
            master_numbers |= _extract_numbers(bullet)
    for proj in master.get("projects", []) or []:
        for bullet in proj.get("bullets", []) or []:
            master_numbers |= _extract_numbers(bullet)

    warnings: list[dict] = []

    summary = tailored.get("summary") or ""
    suspicious = sorted(_extract_numbers(summary) - master_numbers)
    if suspicious:
        warnings.append({
            "location": "summary",
            "tailored_text": summary,
            "suspicious_numbers": suspicious,
        })

    return warnings
