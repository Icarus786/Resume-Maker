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


# Matches "tool/proper-noun-like" tokens: a capitalized word (Power, Tableau,
# AWS), an all-caps acronym (SQL, ETL, KPI), or tokens with internal capitals/
# digits/symbols common to tech names (PyTorch, scikit-learn, C++, Node.js).
# Used to detect a rewritten bullet that NAMES a tool the original didn't.
_TOOL_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9.+#/-]*")

# Common capitalized words that start sentences or are generic - not tools.
# Kept deliberately small; the comparison is against the original bullet's own
# token set, so ordinary shared words never trip the guard anyway.
_TOOL_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "for", "with", "on", "by",
    "at", "as", "from", "into", "led", "built", "created", "developed",
    "designed", "managed", "improved", "increased", "reduced", "delivered",
    "drove", "owned", "analyzed", "implemented", "automated", "collaborated",
    "partnered", "supported", "enabled", "this", "that", "these", "those",
}


def _tool_tokens(text: str) -> set[str]:
    """Lowercased set of tool/proper-noun-like tokens in `text`.

    Keeps only tokens that look like a named tool/technology rather than an
    ordinary word:
    - an acronym (all caps, 2+ chars), e.g. SQL, ETL, KPI;
    - a token with an internal capital/digit/symbol, e.g. PyTorch, C++,
      Node.js, scikit-learn;
    - a Capitalized word that is NOT the first token of the text - the leading
      word of a bullet is almost always an ordinary (often verb) word that
      happens to be capitalized, so flagging it would wrongly reject honest
      reframes that simply swap the opening verb (Built -> Engineered).

    Lowercased so case differences between original and rewrite don't matter;
    common verbs/articles are dropped via stopwords.
    """
    tokens: set[str] = set()
    raws = _TOOL_TOKEN_RE.findall(text)
    for i, raw in enumerate(raws):
        if raw.lower() in _TOOL_STOPWORDS:
            continue
        is_acronym = raw.isupper() and len(raw) >= 2
        has_internal_signal = any(c.isupper() or c.isdigit() for c in raw[1:]) or any(
            c in raw for c in ".+#/"
        )
        is_capitalized = raw[:1].isupper() and i > 0
        if is_acronym or has_internal_signal or is_capitalized:
            tokens.add(raw.lower())
    return tokens


def filter_bullet_rewrites(rewrites: dict[str, str], originals: dict[str, str]) -> dict[str, str]:
    """Keep only bullet rewrites that introduce NO new facts vs. the original.

    `rewrites` and `originals` are both {bullet_id -> text}. A rewrite is
    REVERTED (dropped from the result) if its text contains a numeric token or
    a tool/proper-noun token that does not appear in the corresponding original
    bullet - i.e. the LLM added a metric or named a tool that wasn't there.
    This is the deterministic backstop behind the "never fake experience"
    guarantee: even if the model ignores its instructions, fabricated rewrites
    are silently discarded and the original bullet is used instead.

    Returns the subset of `rewrites` that passed (callers fall back to the
    original text for any id not present in the result).
    """
    kept: dict[str, str] = {}
    for bid, new_text in rewrites.items():
        original = originals.get(bid)
        if original is None:
            continue  # unknown id - ignore
        if new_text.strip() == original.strip():
            continue  # unchanged; nothing to apply
        new_numbers = _extract_numbers(new_text) - _extract_numbers(original)
        new_tools = _tool_tokens(new_text) - _tool_tokens(original)
        if new_numbers or new_tools:
            continue  # introduced a new number or tool -> reject, keep original
        kept[bid] = new_text
    return kept


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

    # Experience/project bullets may now be reworded by the LLM (and are
    # already guarded per-bullet by `filter_bullet_rewrites`). Re-check here as
    # a final backstop: flag any bullet whose numbers don't all appear in the
    # master resume.
    for job in tailored.get("experience", []) or []:
        company = job.get("company", "")
        for bullet in job.get("bullets", []) or []:
            suspicious = sorted(_extract_numbers(bullet) - master_numbers)
            if suspicious:
                warnings.append({
                    "location": f"experience ({company})" if company else "experience",
                    "tailored_text": bullet,
                    "suspicious_numbers": suspicious,
                })
    for proj in tailored.get("projects", []) or []:
        name = proj.get("name", "")
        for bullet in proj.get("bullets", []) or []:
            suspicious = sorted(_extract_numbers(bullet) - master_numbers)
            if suspicious:
                warnings.append({
                    "location": f"project ({name})" if name else "project",
                    "tailored_text": bullet,
                    "suspicious_numbers": suspicious,
                })

    return warnings
