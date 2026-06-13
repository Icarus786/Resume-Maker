"""Ollama client + job-description analysis.

Thin wrapper around the local Ollama HTTP API (`/api/chat`), used in JSON
mode with low temperature for deterministic, structured output. All prompts
live in this module so tailoring/cover-letter logic (Sections 4-5) can build
on `chat_json()`.
"""
from __future__ import annotations

import json
import re

import httpx
import yaml

from app.config import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_TEMPERATURE,
    OLLAMA_TIMEOUT_SECONDS,
    SKILL_CATEGORY_MAP_PATH,
)
from app.honesty_guard import filter_bullet_rewrites


class OllamaError(RuntimeError):
    """Raised when the local Ollama server is unreachable or returns an error."""


def chat_json(system_prompt: str, user_prompt: str, *, temperature: float | None = None) -> dict:
    """Send a chat request to Ollama and parse the response as JSON.

    Uses Ollama's `format: "json"` mode, which constrains the model to emit
    valid JSON. Raises OllamaError on connection failure, HTTP error, or if
    the model's output isn't valid JSON.
    """
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "format": "json",
        "stream": False,
        "options": {
            "temperature": OLLAMA_TEMPERATURE if temperature is None else temperature,
        },
    }

    try:
        resp = httpx.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=payload,
            timeout=OLLAMA_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
    except httpx.ConnectError as exc:
        raise OllamaError(
            f"Could not connect to Ollama at {OLLAMA_BASE_URL}. "
            f"Is it running? (Start with 'ollama serve' or the Ollama app.)"
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise OllamaError(
            f"Ollama returned an error: {exc.response.status_code} {exc.response.text}"
        ) from exc
    except httpx.TimeoutException as exc:
        raise OllamaError(
            f"Ollama request timed out after {OLLAMA_TIMEOUT_SECONDS}s. "
            f"The model may be slow on this hardware - try a smaller model "
            f"or increase OLLAMA_TIMEOUT_SECONDS."
        ) from exc

    data = resp.json()
    content = data.get("message", {}).get("content", "")

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Llama occasionally wraps the JSON in markdown fences or adds stray
    # commentary even in `format: "json"` mode. Strip fences and fall back to
    # extracting the outermost {...} object before giving up.
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise OllamaError(
        f"Ollama did not return valid JSON.\n--- raw content ---\n{content[:2000]}"
    )


# --- Job description analysis ------------------------------------------------

_ANALYZE_SYSTEM_PROMPT = """\
You are an expert technical recruiter and ATS (Applicant Tracking System) \
analyst with a reputation for being EXTREMELY THOROUGH. Your job is to \
extract EVERY SINGLE keyword, skill, tool, qualification, and requirement \
from a job description, so a candidate can maximize their resume's ATS match \
score. Missing a keyword that the ATS scans for could cost the candidate the \
job, so err heavily on the side of including too much rather than too little.

Respond with ONLY a JSON object (no markdown, no commentary) with this exact \
shape:
{
  "job_title": "string - the job title from the posting",
  "company_name": "string - the hiring company's name from the posting",
  "hard_keywords": ["string", ...],
  "soft_keywords": ["string", ...],
  "must_haves": ["string", ...]
}

Definitions:
- "company_name": the name of the company that is hiring, as written in the \
posting (e.g. "Acme Corp"). If the posting does not name the company (e.g. \
it's anonymized or posted by a recruiting agency on behalf of an undisclosed \
client), use an empty string "".
- "hard_keywords": EVERY concrete technical skill, tool, platform, language, \
framework, library, database, cloud service, file format, methodology, \
certification, standard, or technique mentioned ANYWHERE in the posting - \
including in the "nice to have", "responsibilities", "about the team", and \
"about the role" sections, not just "requirements". This includes:
  - Named technologies/tools/platforms (e.g. "Power BI", "SQL", "Python", \
"AWS", "DAX", "Salesforce", "Excel", "Jira").
  - Methodologies and frameworks (e.g. "Agile", "Scrum", "Waterfall", "Six \
Sigma", "ETL", "CI/CD").
  - Both the acronym AND the expanded form when the posting uses or implies \
both (e.g. if the posting says "Key Performance Indicators (KPIs)", include \
both "KPIs" and "Key Performance Indicators"; if it says "SQL" but also \
implies "Structured Query Language" type work, include the form actually \
used).
  - Domain/industry terms that double as ATS keywords (e.g. "data \
visualization", "financial modeling", "supply chain", "regulatory \
compliance", "forecasting", "budgeting", "variance analysis").
  - Job-title-adjacent variants used in the posting (e.g. "Business \
Intelligence", "BI", "Data Analytics").
  - Action-oriented competencies described even briefly, in passing, or as \
part of a longer sentence (e.g. a sentence like "you'll build dashboards and \
automate reporting" yields "dashboards" and "reporting automation").
- "soft_keywords": EVERY soft skill, trait, behavior, or quality the posting \
explicitly mentions or clearly and directly implies through specific wording \
(e.g. "stakeholder communication", "attention to detail", "leadership", \
"cross-functional collaboration", "problem-solving", "time management", \
"adaptability", "ownership", "mentorship"). Do not add generic soft skills \
that aren't grounded in specific words/phrases from the posting.
- "must_haves": EVERY explicit required or strongly preferred qualification, \
credential, years of experience, education level, certification, language \
requirement, work authorization/location requirement, etc. (e.g. "3+ years \
of experience with Power BI", "Bachelor's degree in Computer Science", \
"PMP certification preferred", "must be legally authorized to work in \
Canada"). Capture items from "Requirements", "Qualifications", "Nice to \
Have", and "Preferred" sections alike - do not skip "preferred"/"nice to \
have" items.

Rules:
- Be AGGRESSIVE and EXHAUSTIVE. Re-read the entire posting line by line - \
including bullet points buried in "responsibilities", "day-to-day", or \
"about you" sections - and extract every keyword you find there too, not \
just from an explicit skills/requirements list.
- Keywords should be skills, tools, technologies, methodologies, \
certifications, or competencies - NOT team names, department names, company \
names, or generic nouns like "team" or "role" (e.g. extract "FP&A" or \
"financial planning & analysis" as a domain keyword, but do not extract "the \
FP&A team" or "Operations & Finance analytics team" as a literal phrase).
- Extract only what is actually present or directly and unambiguously implied \
by the job description. Do not invent unrelated requirements or a company \
name that isn't there.
- When the posting uses both an acronym and its expansion (or a tool name and \
its broader category), include both forms as separate keywords - ATS systems \
often match on exact strings.
- Deduplicate near-identical keywords, but prefer keeping multiple closely \
related phrasings (e.g. "data visualization" AND "dashboards" AND "reporting" \
can all coexist if the posting touches on all three) - this is a case where \
more coverage beats over-deduplication.
- Order keywords roughly by importance/frequency in the posting.
- Limit hard_keywords and soft_keywords to at most 40 items each, and \
must_haves to at most 20 items. Use as much of this budget as the posting \
genuinely supports - a thorough posting should usually yield 20-40 \
hard_keywords, not just 6-10.
"""


def analyze_job(jd_text: str) -> dict:
    """Analyze a job description and extract structured keyword data.

    Returns a dict: {job_title, hard_keywords[], soft_keywords[], must_haves[]}.
    Raises OllamaError if the model is unreachable or returns invalid JSON.
    Raises ValueError if `jd_text` is empty/whitespace.
    """
    jd_text = (jd_text or "").strip()
    if not jd_text:
        raise ValueError("Job description text is empty.")

    user_prompt = f"Job description:\n\"\"\"\n{jd_text}\n\"\"\""
    result = chat_json(_ANALYZE_SYSTEM_PROMPT, user_prompt)

    # Normalize shape so callers can rely on these keys/types existing.
    return {
        "job_title": str(result.get("job_title", "") or ""),
        "company_name": str(result.get("company_name", "") or ""),
        "hard_keywords": [str(k) for k in result.get("hard_keywords", []) or []],
        "soft_keywords": [str(k) for k in result.get("soft_keywords", []) or []],
        "must_haves": [str(k) for k in result.get("must_haves", []) or []],
    }


# --- Resume tailoring ---------------------------------------------------------

# Standardized professional names for soft skills / competencies. The job
# description analysis often surfaces soft skills in casual phrasing (e.g.
# "detail-oriented", "team player"); when we weave these into the Core
# Competencies section we map them to a clean, resume-appropriate label.
# Keys are matched case-insensitively against the casual JD wording. Anything
# not in this map is left to the LLM / title-cased as a fallback.
_SOFT_SKILL_CANONICAL = {
    "detail-oriented": "Attention to Detail",
    "detail oriented": "Attention to Detail",
    "attention to detail": "Attention to Detail",
    "strong communicator": "Communication",
    "communicator": "Communication",
    "communication skills": "Communication",
    "verbal communication": "Communication",
    "written communication": "Communication",
    "excellent communication": "Communication",
    "strong communication": "Communication",
    "team player": "Teamwork",
    "teamwork": "Teamwork",
    "collaborative": "Collaboration",
    "collaboration": "Collaboration",
    "cross-functional collaboration": "Cross-Functional Collaboration",
    "cross functional collaboration": "Cross-Functional Collaboration",
    "stakeholder management": "Stakeholder Management",
    "stakeholder engagement": "Stakeholder Engagement",
    "stakeholder communication": "Stakeholder Communication",
    "problem solving": "Problem-Solving",
    "problem-solving": "Problem-Solving",
    "analytical": "Analytical Thinking",
    "analytical thinking": "Analytical Thinking",
    "analytical mindset": "Analytical Thinking",
    "critical thinking": "Critical Thinking",
    "leadership": "Leadership",
    "leader": "Leadership",
    "mentorship": "Mentorship",
    "mentoring": "Mentorship",
    "time management": "Time Management",
    "organized": "Organization",
    "organization": "Organization",
    "organizational skills": "Organization",
    "adaptability": "Adaptability",
    "adaptable": "Adaptability",
    "flexible": "Adaptability",
    "flexibility": "Adaptability",
    "self-motivated": "Self-Motivation",
    "self motivated": "Self-Motivation",
    "self-starter": "Self-Motivation",
    "proactive": "Proactivity",
    "proactivity": "Proactivity",
    "ownership": "Ownership",
    "accountability": "Accountability",
    "accountable": "Accountability",
    "change management": "Change Management",
    "interpersonal": "Interpersonal Skills",
    "interpersonal skills": "Interpersonal Skills",
    "presentation skills": "Presentation Skills",
    "presentation": "Presentation Skills",
    "storytelling": "Data Storytelling",
    "data storytelling": "Data Storytelling",
    "customer focus": "Customer Focus",
    "customer-focused": "Customer Focus",
    "results-driven": "Results Orientation",
    "results oriented": "Results Orientation",
    "results-oriented": "Results Orientation",
    "outcome-oriented": "Results Orientation",
    "negotiation": "Negotiation",
    "decision making": "Decision-Making",
    "decision-making": "Decision-Making",
    "creativity": "Creativity",
    "creative": "Creativity",
    "work ethic": "Strong Work Ethic",
    "multitasking": "Multitasking",
    "conflict resolution": "Conflict Resolution",
    "emotional intelligence": "Emotional Intelligence",
    "continuous improvement": "Continuous Improvement",
    "process improvement": "Process Improvement",
    "independent worker": "Self-Motivation",
    "works independently": "Self-Motivation",
    "ability to work independently": "Self-Motivation",
    "fast learner": "Adaptability",
    "quick learner": "Adaptability",
    "growth mindset": "Adaptability",
    "strong attention to detail": "Attention to Detail",
    "excellent attention to detail": "Attention to Detail",
    "highly detail-oriented": "Attention to Detail",
    "excellent communication skills": "Communication",
    "strong communication skills": "Communication",
    "strong interpersonal skills": "Interpersonal Skills",
    "strong organizational skills": "Organization",
    "ability to multitask": "Multitasking",
    "ability to prioritize": "Time Management",
    "prioritization": "Time Management",
    "deadline-driven": "Time Management",
    "deadline driven": "Time Management",
    "strong analytical skills": "Analytical Thinking",
    "analytical skills": "Analytical Thinking",
    "strong problem-solving skills": "Problem-Solving",
    "problem-solving skills": "Problem-Solving",
    "problem solving skills": "Problem-Solving",
    "team-oriented": "Teamwork",
    "team oriented": "Teamwork",
    "works well under pressure": "Resilience",
    "ability to work under pressure": "Resilience",
    "thrives under pressure": "Resilience",
    "innovative": "Creativity",
    "innovation": "Creativity",
    "strategic thinking": "Strategic Thinking",
    "strategic": "Strategic Thinking",
    "business acumen": "Business Acumen",
    "customer service": "Customer Focus",
    "client-facing": "Customer Focus",
    "client facing": "Customer Focus",
    "relationship building": "Relationship Building",
    "relationship management": "Relationship Building",
    "training and development": "Mentorship",
    "coaching": "Mentorship",
    "documentation": "Documentation",
    "report writing": "Presentation Skills",
    "problem-solving mindset": "Problem-Solving",
    "problem solving mindset": "Problem-Solving",
    "analytical mindset": "Analytical Thinking",
    "curiosity": "Curiosity",
    "intellectual curiosity": "Curiosity",
    "curious mindset": "Curiosity",
    "inquisitive": "Curiosity",
    "inquisitiveness": "Curiosity",
    "initiative": "Proactivity",
    "takes initiative": "Proactivity",
    "resourceful": "Resourcefulness",
    "resourcefulness": "Resourcefulness",
    "willingness to learn": "Continuous Learning",
    "continuous learning": "Continuous Learning",
    "lifelong learner": "Continuous Learning",
    "open-minded": "Adaptability",
    "open minded": "Adaptability",
    "open-mindedness": "Adaptability",
    "open mindedness": "Adaptability",
    "integrity": "Integrity",
    "reliability": "Reliability",
    "dependability": "Reliability",
    "dependable": "Reliability",
}


def _load_skill_category_map() -> dict:
    """Load the persisted keyword -> category routing table.

    See data/skill_category_map.yaml for format and how corrections are
    recorded. A missing/empty file is treated as an empty map so tailoring
    still works before any entries exist.
    """
    if not SKILL_CATEGORY_MAP_PATH.exists():
        return {"hard_skills": {}, "soft_skills": {}}

    raw = yaml.safe_load(SKILL_CATEGORY_MAP_PATH.read_text(encoding="utf-8")) or {}
    return {
        "hard_skills": {
            str(k).strip().lower(): str(v) for k, v in (raw.get("hard_skills") or {}).items()
        },
        "soft_skills": {
            str(k).strip().lower(): str(v) for k, v in (raw.get("soft_skills") or {}).items()
        },
    }


def _yaml_quote(text: str) -> str:
    """Render a string as a double-quoted YAML scalar (escaping backslashes
    and double quotes), matching the style used throughout
    data/skill_category_map.yaml.
    """
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _append_skill_map_entries(new_hard: dict[str, str], new_soft: dict[str, str]) -> None:
    """Append newly-learned keyword -> category mappings to
    data/skill_category_map.yaml so future runs route them deterministically
    without needing the LLM fallback again.

    `new_hard`/`new_soft` map lowercase keyword -> category name. Entries
    that already exist in the file (even under the other section) are
    skipped. New lines are appended as plain `"keyword": "Category"` entries
    at the end of each section, preserving the file's existing comments and
    structure (the file is hand-curated, so we avoid re-serializing it via
    yaml.safe_dump, which would strip all comments).

    A missing file is created with minimal `hard_skills:`/`soft_skills:` keys.
    """
    if not new_hard and not new_soft:
        return

    if SKILL_CATEGORY_MAP_PATH.exists():
        text = SKILL_CATEGORY_MAP_PATH.read_text(encoding="utf-8")
        existing = _load_skill_category_map()
    else:
        text = "hard_skills:\n\nsoft_skills:\n"
        existing = {"hard_skills": {}, "soft_skills": {}}

    hard_to_add = {
        kw: cat for kw, cat in new_hard.items() if kw not in existing["hard_skills"]
    }
    soft_to_add = {
        kw: cat for kw, cat in new_soft.items() if kw not in existing["soft_skills"]
    }
    if not hard_to_add and not soft_to_add:
        return

    lines = text.splitlines()

    def _section_bounds(section_name: str) -> tuple[int, int]:
        """Return (header_idx, insert_idx) for a top-level `section_name:`
        key. `insert_idx` is the line index just after the section's last
        line (before the next top-level key or end of file).
        """
        header_idx = next(
            i for i, line in enumerate(lines) if line.rstrip() == f"{section_name}:"
        )
        insert_idx = len(lines)
        for i in range(header_idx + 1, len(lines)):
            stripped = lines[i]
            if stripped and not stripped[0].isspace() and not stripped.startswith("#"):
                insert_idx = i
                break
        return header_idx, insert_idx

    # Insert soft_skills additions first if it comes after hard_skills, so
    # hard_skills insertion indices computed afterwards remain valid.
    sections_to_update = []
    if hard_to_add:
        sections_to_update.append(("hard_skills", hard_to_add))
    if soft_to_add:
        sections_to_update.append(("soft_skills", soft_to_add))

    # Process sections from bottom to top of the file so earlier insertions
    # don't shift the line numbers of later ones.
    sections_with_bounds = [
        (name, entries, *_section_bounds(name)) for name, entries in sections_to_update
    ]
    sections_with_bounds.sort(key=lambda item: item[3], reverse=True)

    for _name, entries, _header_idx, insert_idx in sections_with_bounds:
        new_lines = [f"  {_yaml_quote(kw)}: {_yaml_quote(cat)}" for kw, cat in entries.items()]
        # Trim trailing blank lines immediately before the insertion point so
        # new entries sit directly after the last existing entry.
        while insert_idx > 0 and lines[insert_idx - 1].strip() == "":
            insert_idx -= 1
        lines[insert_idx:insert_idx] = new_lines

    SKILL_CATEGORY_MAP_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


# Words ignored when checking whether a newly-added competency duplicates the
# MEANING of one that's already present (e.g. "Problem-Solving" vs.
# "Analytical & Problem-Solving Mindset" should be treated as the same idea).
_DEDUP_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "for", "with", "on",
    "skills", "skill", "ability", "abilities", "mindset", "approach",
    "oriented", "orientation", "driven", "minded", "focus", "focused",
    "strong", "excellent", "advanced", "proficiency", "proficient",
    "knowledge", "experience",
}


def _significant_words(text: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-z0-9]+", text.lower())
        if w not in _DEDUP_STOPWORDS
    }


def _dedupe_competencies(by_category: dict, extras: list, orig_groups: list) -> None:
    """Drop newly-added competencies that duplicate the meaning of a
    competency already present elsewhere in `core_competencies` (e.g. don't
    add a new "Problem-Solving" entry when "Analytical & Problem-Solving
    Mindset" already exists in another category).

    A new keyword is dropped if its significant words are a subset of (or a
    superset containing) an already-kept keyword's significant words.
    Keywords already in `orig_groups` are never dropped, and comparisons run
    across the WHOLE section (all categories), not just within one category.
    """
    orig_keywords_lower = {kw.strip().lower() for g in orig_groups for kw in g["keywords"]}
    kept_word_sets: list[set[str]] = [
        words for g in orig_groups for words in (_significant_words(kw) for kw in g["keywords"]) if words
    ]

    def _filter(keywords: list[str]) -> list[str]:
        out = []
        for kw in keywords:
            if kw.strip().lower() in orig_keywords_lower:
                out.append(kw)
                continue
            words = _significant_words(kw)
            if words and any(words <= existing or existing <= words for existing in kept_word_sets):
                continue  # near-duplicate of an existing/kept competency
            out.append(kw)
            if words:
                kept_word_sets.append(words)
        return out

    for key in by_category:
        by_category[key] = _filter(by_category[key])
    for i, (category, keywords) in enumerate(extras):
        extras[i] = (category, _filter(keywords))


def _canonical_soft_skill(keyword: str) -> str:
    """Map a casual soft-skill phrase to a standardized professional label.

    Falls back to the original keyword (with leading/trailing whitespace
    stripped) when there's no curated mapping, so unknown terms still appear
    rather than being dropped.
    """
    key = keyword.strip().lower()
    if key in _SOFT_SKILL_CANONICAL:
        return _SOFT_SKILL_CANONICAL[key]
    return keyword.strip()


# --- Stage 1: reword title_line / summary only ---------------------------------
#
# Deliberately small and flat. Earlier versions of this prompt also asked the
# model to add and (re)categorize every JD keyword into `skills` /
# `core_competencies` in one giant nested-JSON response. Llama (unlike
# Claude/GPT) frequently dropped keywords, invented/merged categories, or
# passed through casual JD wording for soft skills when asked to do all of
# that at once. Keyword addition/categorization is now done deterministically
# in Python (`_merge_jd_keywords`), so this prompt only needs two short
# strings back - a shape Llama handles reliably.
_REWORD_SYSTEM_PROMPT = """\
You are an expert resume writer helping a candidate tailor their EXISTING \
resume to better match a specific job description, for ATS (Applicant \
Tracking System) optimization.

You will be given:
1. The candidate's current `title_line` and `summary`.
2. A structured analysis of the target job description (job title, company, \
hard/soft keywords, must-haves).

Your task:
- Reword `title_line` to mirror the target job title, as long as it remains \
truthful to the candidate's actual background. If no good rewording exists, \
return it unchanged.
- Lightly rewrite `summary` for ATS optimization: improve word choice, \
emphasize the most relevant existing skills/experience first, and weave in JD \
terminology WHERE IT GENUINELY DESCRIBES SOMETHING ALREADY PRESENT in the \
summary. Keep it roughly the same length and meaning.
- Do NOT invent new responsibilities, tools, technologies, employers, titles, \
dates, metrics, skills, or accomplishments that are not already present in \
the candidate's background. Do NOT add new claims.

Respond with ONLY a JSON object (no markdown, no commentary) with this exact \
shape:
{
  "title_line": "string",
  "summary": "string"
}
"""


# --- Stage 0: flag existing categories that don't fit this job ----------------
#
# The candidate's master resume may contain whole skill/competency categories
# that are real and truthful but not relevant to a given job (e.g. a "Machine
# Learning & Forecasting" category when applying to a Business Analyst role).
# `_merge_jd_keywords` never removes original content, so without this step
# such categories would always appear. Here we ask the LLM which EXISTING
# categories are a poor fit for the target job, so `tailor_resume` can move
# them to the end of the section and flag them in the diff as "suggested for
# removal" - the user can still keep them with one click.
_RELEVANCE_SYSTEM_PROMPT = """\
You are helping a candidate tailor their resume to a specific job by deciding \
which of their EXISTING resume section categories are a poor fit for the job.

You will be given:
- `job`: a structured analysis of the target job description (job title, \
hard/soft keywords, must-haves).
- `skill_categories`: the category names in the candidate's "Skills" section.
- `competency_categories`: the category names in the candidate's "Core \
Competencies" section.

For each category name in `skill_categories` and `competency_categories`, \
decide if it is LOW_RELEVANCE for this specific job - meaning the category as \
a whole (its general subject area) has little to do with the job's \
responsibilities or required skills, and including it would look unfocused \
on a tailored resume (e.g. a "Machine Learning & Forecasting" category when \
the job is a Business Analyst role with no ML/forecasting requirements).

Only mark a category LOW_RELEVANCE if it is clearly off-topic for the job. If \
a category is plausibly relevant, generally useful, or related to the job's \
domain even loosely, mark it RELEVANT. Most categories should be RELEVANT - \
be conservative.

Respond with ONLY a JSON object (no markdown, no commentary) with this exact \
shape:
{
  "skill_categories": {"<category name>": "RELEVANT" or "LOW_RELEVANCE", ...},
  "competency_categories": {"<category name>": "RELEVANT" or "LOW_RELEVANCE", ...}
}

Every category name from both input lists MUST appear as a key in the \
matching output object, exactly as given.
"""


def _classify_category_relevance(
    jd_analysis: dict,
    skill_categories: list[str],
    competency_categories: list[str],
) -> tuple[set[str], set[str]]:
    """Ask the LLM which existing resume categories are a poor fit for this job.

    Returns (low_relevance_skill_categories, low_relevance_competency_categories)
    - sets of category names (exactly as given in the inputs) the model marked
    "LOW_RELEVANCE". On any Ollama error or malformed response, returns two
    empty sets (fail open - tailoring proceeds with all categories treated as
    relevant).
    """
    if not skill_categories and not competency_categories:
        return set(), set()

    user_prompt = json.dumps(
        {
            "job": jd_analysis,
            "skill_categories": skill_categories,
            "competency_categories": competency_categories,
        },
        indent=2,
    )
    try:
        result = chat_json(_RELEVANCE_SYSTEM_PROMPT, user_prompt, temperature=0.0)
    except OllamaError:
        return set(), set()

    if not isinstance(result, dict):
        return set(), set()

    def _low_relevance(field: str, valid: list[str]) -> set[str]:
        verdicts = result.get(field)
        if not isinstance(verdicts, dict):
            return set()
        valid_set = set(valid)
        return {
            name
            for name, verdict in verdicts.items()
            if name in valid_set and verdict == "LOW_RELEVANCE"
        }

    return (
        _low_relevance("skill_categories", skill_categories),
        _low_relevance("competency_categories", competency_categories),
    )


# --- Stage 1b: rewrite experience / project bullets for the target role -------
#
# The biggest lever for actually adapting a resume to a different role (e.g. a
# Business-Analyst master resume targeting a Data Scientist posting) is the
# bullet text itself. Previously bullets were copied verbatim. Here we let the
# LLM REFRAME each bullet toward the target job and weave in JD terminology -
# but ONLY where it already describes what the bullet says. Every employer,
# date, metric, tool, and outcome must be preserved; nothing may be invented.
# A deterministic guard (`honesty_guard.filter_bullet_rewrites`) runs AFTER
# this and reverts any rewrite that introduces a number or tool/proper noun
# that wasn't in the original bullet, so fabrication can't slip through even if
# the model ignores the instructions.
_BULLET_REWRITE_SYSTEM_PROMPT = """\
You are an expert resume writer optimizing a candidate's EXISTING experience \
and project bullets for a specific target job and for ATS (Applicant Tracking \
System) keyword matching.

You will be given:
- `target_job`: a structured analysis of the job (title, hard/soft keywords, \
must-haves).
- `bullets`: a flat list of the candidate's real experience/project bullets, \
each with an `id` and `text`.

Rewrite each bullet so it reads as strongly as possible FOR THIS TARGET JOB:
- Lead with the most job-relevant angle of what the bullet describes.
- Use stronger action verbs and clearer outcome framing.
- Weave in terminology from `target_job` ONLY where it genuinely and \
accurately describes what the bullet already says (e.g. if a bullet describes \
building predictive models and the job wants "machine learning", you may use \
"machine learning"; if the bullet has nothing to do with a JD keyword, do NOT \
force that keyword in).

ABSOLUTE RULES - violating these is worse than a weak bullet:
- NEVER invent or change facts. Keep every number, percentage, dollar amount, \
date, employer, team, product, and tool EXACTLY as in the original. Do not add \
a metric, tool, technology, or accomplishment that is not in the original \
bullet.
- NEVER add a named tool/technology/skill the original bullet does not \
mention, even if the job asks for it. Reframing is allowed; fabricating is not.
- If a bullet genuinely cannot be improved without inventing something, return \
it UNCHANGED.
- Keep each rewritten bullet roughly the same length as the original (one \
concise sentence/line).

Respond with ONLY a JSON object (no markdown, no commentary) with this exact \
shape:
{
  "bullets": [{"id": <same id as input>, "text": "<rewritten bullet>"}, ...]
}

Every bullet id from the input MUST appear exactly once in your response.
"""


def _rewrite_experience_bullets(master: dict, jd_analysis: dict) -> dict[str, str]:
    """Rewrite experience/project bullets toward the target job via the LLM.

    Returns {bullet_id -> rewritten text} for ids the model returned with a
    non-empty string. Bullet ids are "exp:<job_index>:<bullet_index>" and
    "proj:<project_index>:<bullet_index>". Callers MUST run the rewrites
    through `honesty_guard.filter_bullet_rewrites` before using them, so any
    rewrite that introduces a new number/tool is reverted to the original.

    On any Ollama error or malformed response returns {} (fail open - bullets
    stay verbatim).
    """
    indexed: list[dict] = []
    for ji, job in enumerate(master.get("experience", []) or []):
        for bi, bullet in enumerate(job.get("bullets", []) or []):
            if str(bullet).strip():
                indexed.append({"id": f"exp:{ji}:{bi}", "text": str(bullet)})
    for pi, proj in enumerate(master.get("projects", []) or []):
        for bi, bullet in enumerate(proj.get("bullets", []) or []):
            if str(bullet).strip():
                indexed.append({"id": f"proj:{pi}:{bi}", "text": str(bullet)})

    if not indexed:
        return {}

    payload = {"target_job": jd_analysis, "bullets": indexed}
    try:
        result = chat_json(
            _BULLET_REWRITE_SYSTEM_PROMPT, json.dumps(payload, indent=2), temperature=0.2
        )
    except OllamaError:
        return {}

    if not isinstance(result, dict):
        return {}

    rewrites: dict[str, str] = {}
    for item in result.get("bullets") or []:
        if not isinstance(item, dict):
            continue
        bid = str(item.get("id", "")).strip()
        text = str(item.get("text", "") or "").strip()
        if bid and text:
            rewrites[bid] = text
    return rewrites


# --- Stage 0b: gap / match analysis against the candidate's real background ----
#
# The core thing GPT/Gemini give you that pure keyword-stuffing does not: an
# honest read on which JD requirements the candidate's actual experience
# supports, which are only partially evidenced, and which are simply missing.
# This judges each JD requirement against the FULL resume (summary + skills +
# experience bullets + project bullets) so the UI can surface a gaps panel and
# the user can decide what to address - instead of blindly listing skills they
# can't back up.
_GAP_SYSTEM_PROMPT = """\
You are a candid career coach comparing a candidate's resume to a target job. \
Your job is to tell the candidate the TRUTH about how well their actual \
experience supports this job's requirements - not to flatter them.

You will be given:
- `resume`: the candidate's real background (summary, skill lists, and the \
bullet points from their experience and projects). This is the ONLY evidence \
of what they can actually do.
- `requirements`: the job's must-haves and key hard skills.

For EACH requirement, judge two things:

(A) how well the resume's evidence supports it (`status`):
- "strong": the resume clearly demonstrates this through concrete experience, \
projects, or skills.
- "partial": the resume shows related/adjacent experience but not a direct, \
clear match (e.g. requirement is "Power BI" and the resume shows Tableau and \
general dashboarding, but not Power BI specifically).
- "missing": nothing in the resume supports this requirement.

(B) how important it is to THIS job (`importance`):
- "critical": a core, must-have skill the job clearly centers on or lists as a \
hard requirement - missing it would seriously weaken the application.
- "nice_to_have": a secondary, optional, or peripheral keyword - a bonus, not \
a dealbreaker.
Be selective: only a handful of the requirements should be "critical". When in \
doubt, choose "nice_to_have".

Be honest and conservative on status: do NOT rate something "strong" unless the \
resume genuinely backs it up. A keyword merely appearing in a skills list, with \
no supporting experience, is at most "partial".

Then write 1-3 short, specific, actionable suggestions for the biggest gaps \
(the "missing"/"partial" items that matter most for this job) - e.g. which \
real experience to emphasize, or which genuine skill the candidate should add \
to their master resume if they actually have it. Never tell the candidate to \
fabricate experience.

Respond with ONLY a JSON object (no markdown, no commentary) with this exact \
shape:
{
  "requirements": [
    {"requirement": "<requirement text, exactly as given>",
     "status": "strong" or "partial" or "missing",
     "importance": "critical" or "nice_to_have",
     "evidence": "<one short phrase citing what in the resume supports it, \
or empty string if missing>"},
    ...
  ],
  "suggestions": ["<short actionable suggestion>", ...]
}

Every requirement from the input MUST appear exactly once in `requirements`.
"""


def _resume_evidence(master: dict) -> dict:
    """Condense the master resume into just the evidence relevant to gap
    analysis - summary, flat skill list, and experience/project bullets -
    keeping the prompt focused and small."""
    skills = [
        kw for group in master.get("skills", []) for kw in group.get("keywords", [])
    ]
    skills += [
        kw for group in master.get("core_competencies", []) for kw in group.get("keywords", [])
    ]
    experience = [
        {"title": job.get("title", ""), "company": job.get("company", ""), "bullets": job.get("bullets", [])}
        for job in master.get("experience", [])
    ]
    projects = [
        {"name": proj.get("name", ""), "bullets": proj.get("bullets", [])}
        for proj in master.get("projects", [])
    ]
    return {
        "summary": master.get("summary") or "",
        "skills": skills,
        "experience": experience,
        "projects": projects,
    }


def analyze_gaps(master: dict, jd_analysis: dict) -> dict:
    """Judge how well the candidate's real background supports the job.

    Returns {"requirements": [{requirement, status, importance, evidence}, ...],
             "suggestions": [str, ...],
             "suggested_skills": [str, ...]}, where status is
    "strong"/"partial"/"missing" and importance is "critical"/"nice_to_have".

    `suggested_skills` is the subset worth proactively offering to add to the
    resume: requirements judged "critical" importance, NOT already on the
    resume, and only "missing"/"partial" in status (skills the candidate may
    genuinely have but didn't list). The UI surfaces these as an opt-in
    checklist so the user can include a crucial skill they actually possess
    (e.g. "data lakehouse") instead of it silently never appearing. We never
    auto-add them - the user must confirm.

    On any Ollama error or malformed response returns empty lists (fail open).
    """
    requirements = list(
        dict.fromkeys(
            [str(r) for r in (jd_analysis.get("must_haves") or []) if str(r).strip()]
            + [str(k) for k in (jd_analysis.get("hard_keywords") or []) if str(k).strip()]
        )
    )
    if not requirements:
        return {"requirements": [], "suggestions": [], "suggested_skills": []}

    payload = {
        "resume": _resume_evidence(master),
        "requirements": requirements,
    }
    try:
        result = chat_json(_GAP_SYSTEM_PROMPT, json.dumps(payload, indent=2), temperature=0.0)
    except OllamaError:
        return {"requirements": [], "suggestions": [], "suggested_skills": []}

    if not isinstance(result, dict):
        return {"requirements": [], "suggestions": [], "suggested_skills": []}

    # Skills already on the resume (any section), for excluding from suggestions.
    present_lower = {
        kw.strip().lower()
        for group in (master.get("skills", []) or []) + (master.get("core_competencies", []) or [])
        for kw in group.get("keywords", []) or []
    }

    valid_status = {"strong", "partial", "missing"}
    requirements_out = []
    suggested_skills: list[str] = []
    for item in result.get("requirements") or []:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "")).strip().lower()
        if status not in valid_status:
            continue
        requirement = str(item.get("requirement", "")).strip()
        importance = str(item.get("importance", "")).strip().lower()
        if importance not in {"critical", "nice_to_have"}:
            importance = "nice_to_have"
        requirements_out.append(
            {
                "requirement": requirement,
                "status": status,
                "importance": importance,
                "evidence": str(item.get("evidence", "") or "").strip(),
            }
        )
        # Crucial skill the resume doesn't clearly have -> offer to add it.
        if (
            importance == "critical"
            and status in {"missing", "partial"}
            and requirement
            and requirement.strip().lower() not in present_lower
        ):
            suggested_skills.append(requirement)

    suggestions = [str(s).strip() for s in (result.get("suggestions") or []) if str(s).strip()]
    return {
        "requirements": requirements_out,
        "suggestions": suggestions,
        "suggested_skills": suggested_skills,
    }


# --- Stage 3b: auto-categorize keywords with no route-map entry ---------------
#
# When a JD keyword has no entry in skill_category_map.yaml, the old behavior
# was to immediately stop and ask the user which category it belongs in. That
# is friction with little payoff. Instead, we first ask the LLM to place each
# unmatched keyword into one of the candidate's EXISTING categories, the
# catch-all, or to DROP it entirely (when it isn't a real, resume-appropriate
# skill). Only keywords the LLM itself can't place (returns "ASK") fall through
# to the user prompt. Placements into a real category are persisted to the
# route map so future runs are deterministic.
_AUTO_CATEGORIZE_SYSTEM_PROMPT = """\
You are organizing skill keywords pulled from a job description into the \
correct section of a candidate's resume.

You will be given:
- `categories`: the names of the candidate's EXISTING skill/competency \
categories on this resume section.
- `catch_all`: the name of a generic catch-all category to use for real \
skills that don't fit any existing category well.
- `keywords`: keywords from the job description that need to be placed.

For each keyword, choose exactly ONE of:
- The name of one of the EXISTING `categories`, if the keyword clearly belongs \
to that category's subject area.
- The `catch_all` name, if the keyword is a real, resume-appropriate skill / \
tool / competency but doesn't fit any existing category.
- "DROP", if the keyword is NOT a real, resume-appropriate skill - for \
example it describes the job/role itself ("high-impact analytics role", \
"fast-paced environment"), is a generic filler phrase, a department/team \
name, or a sentence fragment rather than a skill label.
- "ASK", ONLY if you genuinely cannot tell where it belongs and it might be a \
real skill - use this sparingly; prefer making a decision.

Respond with ONLY a JSON object (no markdown, no commentary) mapping each \
keyword (exactly as given) to your choice:
{
  "<keyword>": "<existing category name>" or "<catch_all name>" or "DROP" \
or "ASK",
  ...
}

Every keyword from the input MUST appear as a key in your response, exactly \
as given.
"""


def _auto_categorize_keywords(
    keywords: list[str],
    categories: list[str],
    catch_all: str,
) -> dict[str, str]:
    """Ask the LLM to place each unmatched keyword into an existing category,
    the catch-all, DROP, or ASK.

    Returns {keyword -> decision}, where decision is one of: an exact name
    from `categories`, `catch_all`, "DROP", or "ASK". Keywords the model
    omits, or maps to an unrecognized value, default to "ASK" so they fall
    through to the user rather than being silently mishandled. On any Ollama
    error returns "ASK" for every keyword (fail open to the user prompt).
    """
    if not keywords:
        return {}

    valid_targets = set(categories) | {catch_all}
    payload = {
        "categories": categories,
        "catch_all": catch_all,
        "keywords": keywords,
    }
    try:
        result = chat_json(
            _AUTO_CATEGORIZE_SYSTEM_PROMPT, json.dumps(payload, indent=2), temperature=0.0
        )
    except OllamaError:
        return {kw: "ASK" for kw in keywords}

    if not isinstance(result, dict):
        return {kw: "ASK" for kw in keywords}

    decisions: dict[str, str] = {}
    for kw in keywords:
        choice = result.get(kw)
        if choice in valid_targets or choice in ("DROP", "ASK"):
            decisions[kw] = choice
        else:
            decisions[kw] = "ASK"
    return decisions


# --- Stage 4: verify newly-added keywords -------------------------------------
#
# `_merge_jd_keywords` adds JD keywords deterministically, but a JD keyword
# can itself be junk (e.g. analyze_job occasionally extracts a role
# descriptor like "high-impact analytics role" as a soft_keyword - not a
# real competency) or can duplicate the MEANING of an existing item without
# any textual word overlap (so `_dedupe_competencies`'s subset check misses
# it). This pass asks the LLM to review ONLY the newly-added items - never
# the candidate's original content - against the full resume context, and
# drop ones that aren't real skills/competencies or that restate something
# already present.
_VERIFY_SYSTEM_PROMPT = """\
You are doing quality control on a resume's skill/competency lists.

You will be given:
- `existing`: items already on the candidate's resume (grouped by category). \
These are correct and must NOT be flagged.
- `new_items`: items that were just added (grouped by category). Review ONLY \
these.

For each item in `new_items`, decide whether to KEEP or REMOVE it:
- REMOVE an item if it is NOT a real, resume-appropriate skill, tool, or \
competency - for example, it describes the JOB/ROLE itself rather than a \
skill (e.g. "high-impact analytics role", "fast-paced environment"), is a \
generic filler phrase, or is a sentence fragment rather than a skill/\
competency label.
- REMOVE an item if it duplicates the MEANING of an item already in \
`existing` (in any category) or of another item being KEPT in `new_items` \
- even if the wording is different (e.g. "Analytics-Driven Mindset" \
duplicates "Analytical & Problem-Solving Mindset").
- Otherwise KEEP it.

Respond with ONLY a JSON object (no markdown, no commentary) mapping each \
input item (exactly as given) to "KEEP" or "REMOVE":
{
  "<item>": "KEEP" or "REMOVE",
  ...
}

Every item from every category in `new_items` MUST appear as a key in your \
response, exactly as given.
"""


def _verify_additions(
    by_category: dict[str, list[str]],
    added_by_category: dict[str, list[str]],
    extras: list[tuple[str, list[str]]],
) -> None:
    """Review newly-added keywords and drop ones that are junk or
    meaning-duplicates, mutating `by_category` (from `_merge_jd_keywords`,
    possibly already filtered by `_dedupe_competencies`) and `extras` in
    place.

    Only items recorded in `added_by_category`/`extras` (i.e. NOT part of the
    candidate's original resume) are ever removed - original content is
    passed as read-only context (`existing`) and is never flagged. Items a
    prior dedup pass already removed are skipped (they're no longer present
    in `by_category`).

    On any Ollama error, this is a no-op (fail open) so tailoring still
    succeeds offline.
    """
    # Only consider additions that are still present (a prior dedup pass may
    # have already removed some).
    still_added: dict[str, list[str]] = {
        key: [kw for kw in kws if kw in by_category.get(key, [])]
        for key, kws in added_by_category.items()
    }
    new_items = [kw for kws in still_added.values() for kw in kws]
    new_items += [kw for _category, kws in extras for kw in kws]
    if not new_items:
        return

    existing_items = {
        kw
        for key, kws in by_category.items()
        for kw in kws
        if kw not in still_added.get(key, [])
    }

    payload = {
        "existing": sorted(existing_items),
        "new_items": new_items,
    }
    try:
        result = chat_json(_VERIFY_SYSTEM_PROMPT, json.dumps(payload, indent=2), temperature=0.0)
    except OllamaError:
        return

    if not isinstance(result, dict):
        return

    def _keep(kw: str) -> bool:
        # Default to KEEP on missing/invalid entries - never silently drop a
        # keyword just because the model omitted it from its response.
        verdict = result.get(kw)
        return verdict != "REMOVE"

    for key, kws in still_added.items():
        if not kws:
            continue
        remove_set = {kw for kw in kws if not _keep(kw)}
        if remove_set:
            by_category[key] = [kw for kw in by_category[key] if kw not in remove_set]

    for i, (category, kws) in enumerate(extras):
        extras[i] = (category, [kw for kw in kws if _keep(kw)])


def _merge_jd_keywords(
    orig_groups: list[dict],
    jd_keywords: list[str],
    route_map: dict[str, str],
    extra_category_name: str,
    *,
    canonicalize=None,
    learned: dict[str, str] | None = None,
    category_overrides: dict[str, str] | None = None,
) -> tuple[dict[str, list[str]], list[tuple[str, list[str]]], dict[str, list[str]], list[str]]:
    """Deterministically merge `jd_keywords` into a resume section.

    Starts from `orig_groups` verbatim (so nothing the user wrote can ever be
    dropped) and adds each JD keyword that isn't already present:
    1. If `canonicalize` is given, map the keyword to its standardized label
       first (e.g. "detail-oriented" -> "Attention to Detail").
    2. Skip if a keyword with the same significant words already exists
       anywhere in the section (`_significant_words`/near-duplicate check).
    3. Look the (canonical, lowercase) keyword up in `route_map`
       (data/skill_category_map.yaml). If it names an existing category,
       append there.
    4. Otherwise, look it up in `category_overrides` (lowercase keyword ->
       category name or `extra_category_name`/"__OTHER__" for the catch-all),
       which holds choices the user already made for this run via the
       categorization prompt. If present, route there.
    5. Otherwise, the keyword is unresolved: record it in
       `needs_categorization` so the caller can ask the user, and do NOT add
       it to any section yet.

    Newly-resolved (keyword -> category) pairs from steps 3-4 are recorded
    into `learned` (if provided) so the caller can persist them to
    skill_category_map.yaml.

    Returns (by_category, extras, added_by_category, needs_categorization):
    - by_category: {orig category name lowercased -> keywords list}, seeded
      from `orig_groups` (mutated copies, originals never removed).
    - extras: [(extra_category_name, [new keywords...])] - a single extra
      group, present only if at least one keyword landed there.
    - added_by_category: {orig category name lowercased -> [newly-added
      keywords]} - only the keywords appended during this call (i.e. NOT
      part of `orig_groups`), so callers can run a verification/cleanup pass
      over just the new additions without touching the user's original
      content.
    - needs_categorization: [keyword, ...] - keywords with no route-map entry
      and no matching `category_overrides` entry. The caller should ask the
      user which category each belongs to and re-run with those choices in
      `category_overrides`.
    """
    by_category: dict[str, list[str]] = {
        g["category"].strip().lower(): list(g["keywords"]) for g in orig_groups
    }
    category_display = {g["category"].strip().lower(): g["category"] for g in orig_groups}
    added_by_category: dict[str, list[str]] = {key: [] for key in by_category}

    kept_word_sets: list[set[str]] = [
        words
        for kws in by_category.values()
        for words in (_significant_words(kw) for kw in kws)
        if words
    ]
    present_lower: set[str] = {
        kw.strip().lower() for kws in by_category.values() for kw in kws
    }

    extra_keywords: list[str] = []

    def _is_duplicate(kw: str) -> bool:
        if kw.strip().lower() in present_lower:
            return True
        words = _significant_words(kw)
        return bool(words) and any(
            words <= existing or existing <= words for existing in kept_word_sets
        )

    def _record(kw: str, words: set[str]) -> None:
        present_lower.add(kw.strip().lower())
        if words:
            kept_word_sets.append(words)

    # Pass 1: keywords resolvable via the persisted route map.
    pending: list[str] = []
    for kw in jd_keywords:
        kw = str(kw).strip()
        if not kw:
            continue
        label = canonicalize(kw) if canonicalize else kw
        if _is_duplicate(label):
            continue
        target_category = route_map.get(label.strip().lower())
        target_key = target_category.strip().lower() if target_category else None
        if target_key and target_key in by_category:
            by_category[target_key].append(label)
            added_by_category[target_key].append(label)
            _record(label, _significant_words(label))
        else:
            pending.append(label)

    # Pass 2: keywords with no route-map entry - resolve via user-provided
    # `category_overrides`, or flag for the user to categorize.
    if pending:
        # Re-check duplicates (canonicalization in pass 1 may have produced
        # the same label for two different JD keywords).
        pending = [kw for kw in pending if not _is_duplicate(kw)]

    needs_categorization: list[str] = []
    overrides = category_overrides or {}
    for kw in pending:
        if _is_duplicate(kw):
            continue
        chosen = overrides.get(kw.strip().lower())
        if chosen is None:
            needs_categorization.append(kw)
            continue
        target_key = chosen.strip().lower()
        if chosen != "__OTHER__" and target_key in by_category:
            by_category[target_key].append(kw)
            added_by_category[target_key].append(kw)
            if learned is not None:
                learned[kw.strip().lower()] = category_display[target_key]
        else:
            extra_keywords.append(kw)
        _record(kw, _significant_words(kw))

    extras: list[tuple[str, list[str]]] = []
    if extra_keywords:
        extras.append((extra_category_name, extra_keywords))

    return by_category, extras, added_by_category, needs_categorization


def tailor_resume(
    master: dict,
    jd_analysis: dict,
    category_overrides: dict[str, str] | None = None,
) -> dict:
    """Reword/reorder an existing resume to match a job description.

    `master` is a resume dict (e.g. from `resume_to_dict()`).
    `jd_analysis` is the dict returned by `analyze_job()`.
    `category_overrides` (optional) maps lowercase JD keyword -> category
    name (or "__OTHER__"/the section's "Additional ..." catch-all name),
    for keywords the user has already categorized via the UI prompt (see
    `needs_categorization` below).

    NOTE: experience/project bullets MAY now be reworded by the LLM to better
    fit the target role and ATS (`_rewrite_experience_bullets`), but ONLY
    reframing - every number, tool, employer, date and outcome is preserved.
    `honesty_guard.filter_bullet_rewrites` deterministically reverts any
    rewrite that introduces a new number or names a tool absent from the
    original bullet, so facts are never fabricated. Structural fields
    (companies, titles, dates) are always copied verbatim.

    Returns EITHER:
        {"needs_categorization": [{"keyword": str, "categories": [str, ...],
                                    "extra_category": str}, ...]}
      ONLY when JD keywords have no entry in skill_category_map.yaml, no
      matching `category_overrides`, AND the LLM auto-categorizer
      (`_auto_categorize_keywords`) also couldn't place them ("ASK"). This is
      now rare - the LLM places or drops most unmapped keywords itself. The
      caller should ask the user which category each remaining keyword belongs
      to, then re-call with those choices in `category_overrides`.

    OR, once every unmapped keyword is placed/dropped:
        {
          "tailored_resume": dict,   # full resume dict, same shape as `master`,
                                      # with title_line/skills replaced by
                                      # tailored versions (everything else,
                                      # including experience and projects,
                                      # copied from master)
          "diff": {
              "title_line": {"original": str, "tailored": str},
              "skills": [{"category": str, "original": [...], "tailored": [...],
                          "low_relevance": bool}],
              "core_competencies": [{"category": str, "original": [...],
                                      "tailored": [...], "low_relevance": bool}],
              "experience": [{"label": str, "sublabel": str,
                               "bullets": [{"original": str, "tailored": str}]}],
              "projects": [{"label": str, "sublabel": str,
                             "bullets": [{"original": str, "tailored": str}]}],
          },
          "gap_report": {
              "requirements": [{"requirement": str,
                                 "status": "strong"|"partial"|"missing",
                                 "importance": "critical"|"nice_to_have",
                                 "evidence": str}, ...],
              "suggestions": [str, ...],
              "suggested_skills": [str, ...],  # crucial skills the resume
                  # lacks, offered to the user to opt into (see analyze_gaps).
          },   # honest read on which JD requirements the real background
               # supports; see `analyze_gaps`. Empty lists if the LLM errored.
        }

    Categories flagged `"low_relevance": true` are existing categories the
    LLM judged a poor fit for this job (see `_classify_category_relevance`);
    they are moved to the end of their section but never removed - the UI
    should surface them as "suggested for removal" and let the user decide.

    Approach: `title_line`/`summary` rewording is delegated to the LLM (a
    small, flat request it handles reliably). Adding JD keywords into
    `skills`/`core_competencies` and choosing their categories is done
    deterministically in Python via `_merge_jd_keywords`, using
    data/skill_category_map.yaml plus `category_overrides` for keywords with
    no map entry. Each section may gain at most one new category beyond
    those in `master` (an "Additional Skills"/"Additional Competencies"
    catch-all for keywords the user routes there); such a new category has
    `"original": []` in the diff.

    Raises OllamaError on connection/JSON issues with the reword step.
    """
    orig_skills = master.get("skills", [])
    orig_competencies = master.get("core_competencies", [])

    # --- Stage 2/3: deterministically merge JD keywords into skills/competencies ---
    # Done before the (expensive) reword LLM call so we can short-circuit and
    # ask the user about unmapped keywords without wasting that call.
    skill_category_map = _load_skill_category_map()
    learned_hard: dict[str, str] = {}
    learned_soft: dict[str, str] = {}

    skills_by_cat, skills_extras, skills_added, skills_needs_cat = _merge_jd_keywords(
        orig_skills,
        jd_analysis.get("hard_keywords", []) or [],
        skill_category_map["hard_skills"],
        "Additional Skills",
        learned=learned_hard,
        category_overrides=category_overrides,
    )
    comp_by_cat, comp_extras, comp_added, comp_needs_cat = _merge_jd_keywords(
        orig_competencies,
        jd_analysis.get("soft_keywords", []) or [],
        skill_category_map["soft_skills"],
        "Additional Competencies",
        canonicalize=_canonical_soft_skill,
        learned=learned_soft,
        category_overrides=category_overrides,
    )

    # --- Stage 3b: let the LLM place unmatched keywords before asking the user ---
    # Any keyword with no route-map entry and no user override lands in
    # *_needs_cat. Rather than immediately prompting the user, ask the LLM to
    # categorize / drop each. Only keywords the LLM also can't place ("ASK")
    # fall through to the user. Decisions are folded into category_overrides
    # and the merge is re-run so the placements actually take effect (and get
    # persisted to the route map).
    if skills_needs_cat or comp_needs_cat:
        auto_overrides: dict[str, str] = dict(category_overrides or {})
        still_unresolved_skills: list[str] = []
        still_unresolved_comps: list[str] = []

        skill_decisions = _auto_categorize_keywords(
            skills_needs_cat, [g["category"] for g in orig_skills], "Additional Skills"
        )
        comp_decisions = _auto_categorize_keywords(
            comp_needs_cat, [g["category"] for g in orig_competencies], "Additional Competencies"
        )

        for kw, decision in skill_decisions.items():
            if decision == "ASK":
                still_unresolved_skills.append(kw)
            elif decision == "DROP":
                pass  # not a real skill - silently omit
            else:
                auto_overrides[kw.strip().lower()] = decision
        for kw, decision in comp_decisions.items():
            if decision == "ASK":
                still_unresolved_comps.append(kw)
            elif decision == "DROP":
                pass
            else:
                auto_overrides[kw.strip().lower()] = decision

        # Re-run the merge with the LLM's placements applied. Keywords the LLM
        # routed to a catch-all ("Additional ...") resolve there; ones it
        # routed to a real category get appended (and learned/persisted).
        skills_by_cat, skills_extras, skills_added, _ = _merge_jd_keywords(
            orig_skills,
            jd_analysis.get("hard_keywords", []) or [],
            skill_category_map["hard_skills"],
            "Additional Skills",
            learned=learned_hard,
            category_overrides=auto_overrides,
        )
        comp_by_cat, comp_extras, comp_added, _ = _merge_jd_keywords(
            orig_competencies,
            jd_analysis.get("soft_keywords", []) or [],
            skill_category_map["soft_skills"],
            "Additional Competencies",
            canonicalize=_canonical_soft_skill,
            learned=learned_soft,
            category_overrides=auto_overrides,
        )

        # Only genuinely unplaceable keywords still go to the user.
        if still_unresolved_skills or still_unresolved_comps:
            needs_categorization = [
                {
                    "keyword": kw,
                    "categories": [g["category"] for g in orig_skills],
                    "extra_category": "Additional Skills",
                }
                for kw in still_unresolved_skills
            ] + [
                {
                    "keyword": kw,
                    "categories": [g["category"] for g in orig_competencies],
                    "extra_category": "Additional Competencies",
                }
                for kw in still_unresolved_comps
            ]
            return {"needs_categorization": needs_categorization}

    # --- Stage 1: LLM rewords title_line/summary only (flat, small prompt) ---
    reword_prompt = (
        "Current title_line and summary:\n"
        f"{json.dumps({'title_line': master.get('title_line') or '', 'summary': master.get('summary') or ''}, indent=2)}\n\n"
        "Job description analysis:\n"
        f"{json.dumps(jd_analysis, indent=2)}"
    )
    reworded = chat_json(_REWORD_SYSTEM_PROMPT, reword_prompt)

    new_title_line = str(reworded.get("title_line") or master.get("title_line") or "")
    new_summary = str(reworded.get("summary") or master.get("summary") or "")

    # Drop newly-added competencies that just restate an existing one in
    # different words (e.g. a new "Problem-Solving" when "Analytical &
    # Problem-Solving Mindset" is already on the resume).
    _dedupe_competencies(comp_by_cat, comp_extras, orig_competencies)

    # Persist any newly-learned keyword -> category mappings so future runs
    # route them deterministically without the LLM fallback.
    _append_skill_map_entries(learned_hard, learned_soft)

    # --- Stage 4: verify newly-added items are real and non-duplicative ---
    # Catches JD keywords that were never real skills/competencies (e.g.
    # analyze_job extracting a role descriptor like "high-impact analytics
    # role" as a soft_keyword) and meaning-level duplicates the textual dedup
    # above can miss. Only items added in this run are eligible for removal -
    # the candidate's original resume content is never touched.
    _verify_additions(skills_by_cat, skills_added, skills_extras)
    _verify_additions(comp_by_cat, comp_added, comp_extras)

    # --- Stage 0: flag existing categories that don't fit this job ---------
    # Reorders categories so ones unrelated to this job sink to the bottom and
    # are flagged in the diff as "suggested for removal" - the candidate's
    # content is never deleted, only reordered/flagged. Fails open (treats
    # everything as relevant) on any Ollama error.
    skill_category_names = [g["category"] for g in orig_skills]
    comp_category_names = [g["category"] for g in orig_competencies]
    low_relevance_skills, low_relevance_comps = _classify_category_relevance(
        jd_analysis, skill_category_names, comp_category_names
    )

    def _assemble(orig_groups, by_category, extras, low_relevance: set[str]) -> list[dict]:
        """Rebuild a section in original category order (relevant categories
        first, low-relevance ones last), then append any new categories the
        model introduced."""
        groups = [
            {"category": g["category"], "keywords": by_category[g["category"].strip().lower()]}
            for g in orig_groups
            if g["category"] not in low_relevance
        ] + [
            {"category": g["category"], "keywords": by_category[g["category"].strip().lower()]}
            for g in orig_groups
            if g["category"] in low_relevance
        ]
        for category, keywords in extras:
            if category and keywords:
                groups.append({"category": category, "keywords": keywords})
        return groups

    def _section_diff(orig_groups, by_category, extras, low_relevance: set[str]) -> list[dict]:
        def _group(g: dict) -> dict:
            return {
                "category": g["category"],
                "original": list(g["keywords"]),
                "tailored": by_category[g["category"].strip().lower()],
                "low_relevance": g["category"] in low_relevance,
            }

        ordered = [g for g in orig_groups if g["category"] not in low_relevance] + [
            g for g in orig_groups if g["category"] in low_relevance
        ]
        return [_group(g) for g in ordered] + [
            {"category": category, "original": [], "tailored": keywords, "low_relevance": False}
            for category, keywords in extras
            if category and keywords
        ]

    def _bullet_section_diff(items, id_prefix, label_key, sub_key, rewrites) -> list[dict]:
        """Per-entry diff of experience/project bullets, showing each bullet's
        original vs. rewritten text (rewritten == original when no guard-
        approved rewrite exists). `label_key`/`sub_key` name the heading fields
        (e.g. company/title)."""
        out = []
        for idx, item in enumerate(items):
            bullets = item.get("bullets", []) or []
            out.append(
                {
                    "label": item.get(label_key, "") or "",
                    "sublabel": (item.get(sub_key, "") or "") if sub_key else "",
                    "bullets": [
                        {
                            "original": str(b),
                            "tailored": rewrites.get(f"{id_prefix}:{idx}:{bi}", str(b)),
                        }
                        for bi, b in enumerate(bullets)
                    ],
                }
            )
        return out

    # --- Stage 1b: rewrite experience/project bullets toward the target role ---
    # The LLM reframes each bullet for the job; `filter_bullet_rewrites` then
    # reverts any rewrite that introduced a new number or named a tool not in
    # the original, so facts/metrics/tools can never be fabricated. Ids encode
    # position so we can map rewrites back onto the right bullet.
    raw_rewrites = _rewrite_experience_bullets(master, jd_analysis)
    bullet_originals: dict[str, str] = {}
    for ji, job in enumerate(master.get("experience", []) or []):
        for bi, bullet in enumerate(job.get("bullets", []) or []):
            bullet_originals[f"exp:{ji}:{bi}"] = str(bullet)
    for pi, proj in enumerate(master.get("projects", []) or []):
        for bi, bullet in enumerate(proj.get("bullets", []) or []):
            bullet_originals[f"proj:{pi}:{bi}"] = str(bullet)
    bullet_rewrites = filter_bullet_rewrites(raw_rewrites, bullet_originals)

    # --- Build the full tailored resume dict (copy master, replace allowed fields) ---
    tailored_resume = json.loads(json.dumps(master))  # deep copy

    tailored_resume["title_line"] = new_title_line
    tailored_resume["summary"] = new_summary
    tailored_resume["skills"] = _assemble(orig_skills, skills_by_cat, skills_extras, low_relevance_skills)
    tailored_resume["core_competencies"] = _assemble(
        orig_competencies, comp_by_cat, comp_extras, low_relevance_comps
    )

    # Apply the (guard-approved) bullet rewrites onto experience/projects.
    # Facts are preserved; only phrasing/emphasis changes. Bullets with no
    # surviving rewrite keep their original text.
    for ji, job in enumerate(tailored_resume.get("experience", []) or []):
        job["bullets"] = [
            bullet_rewrites.get(f"exp:{ji}:{bi}", b)
            for bi, b in enumerate(job.get("bullets", []) or [])
        ]
    for pi, proj in enumerate(tailored_resume.get("projects", []) or []):
        proj["bullets"] = [
            bullet_rewrites.get(f"proj:{pi}:{bi}", b)
            for bi, b in enumerate(proj.get("bullets", []) or [])
        ]

    # --- Build diff structure for the UI --------------------------------------
    diff = {
        "title_line": {
            "original": master.get("title_line") or "",
            "tailored": new_title_line,
        },
        "summary": {
            "original": master.get("summary") or "",
            "tailored": new_summary,
        },
        "skills": _section_diff(orig_skills, skills_by_cat, skills_extras, low_relevance_skills),
        "core_competencies": _section_diff(
            orig_competencies, comp_by_cat, comp_extras, low_relevance_comps
        ),
        "experience": _bullet_section_diff(
            master.get("experience", []) or [], "exp", "company", "title", bullet_rewrites
        ),
        "projects": _bullet_section_diff(
            master.get("projects", []) or [], "proj", "name", None, bullet_rewrites
        ),
    }

    # --- Gap / match analysis: how well the real background fits this job ---
    gap_report = analyze_gaps(master, jd_analysis)

    return {
        "tailored_resume": tailored_resume,
        "diff": diff,
        "gap_report": gap_report,
    }


def add_skills_to_resume(skills_section: list[dict], skill_names: list[str]) -> list[dict]:
    """Insert user-confirmed skills into a resume's `skills` section.

    Used when the user opts into crucial JD skills the resume lacked (see
    `analyze_gaps` -> `suggested_skills`). Each name is routed to a category
    via data/skill_category_map.yaml, then the LLM auto-categorizer for any
    without a map entry (falling back to an "Additional Skills" catch-all if
    even that can't place it). Newly-learned routes are persisted so future
    runs are deterministic. Skills already present (by near-duplicate match)
    are skipped.

    `skills_section` is the tailored resume's `skills` list (list of
    {category, keywords}); it is NOT mutated. Returns a NEW skills section
    list with the confirmed skills inserted into their categories (a new
    "Additional Skills" group is appended only if needed).
    """
    names = [str(s).strip() for s in skill_names if str(s).strip()]
    if not names:
        return [dict(g) for g in skills_section]

    route_map = _load_skill_category_map()["hard_skills"]
    learned: dict[str, str] = {}

    # First merge what the route map can resolve; collect the rest.
    by_cat, extras, _added, needs_cat = _merge_jd_keywords(
        skills_section, names, route_map, "Additional Skills", learned=learned
    )

    # Auto-categorize anything unmapped; fall back to catch-all (never "ASK"
    # here - the user already confirmed they want these in, so we must place
    # them rather than prompt again).
    if needs_cat:
        decisions = _auto_categorize_keywords(
            needs_cat, [g["category"] for g in skills_section], "Additional Skills"
        )
        overrides = {
            kw.strip().lower(): (dec if dec not in ("ASK", "DROP") else "Additional Skills")
            for kw, dec in decisions.items()
        }
        by_cat, extras, _added, _ = _merge_jd_keywords(
            skills_section, names, route_map, "Additional Skills",
            learned=learned, category_overrides=overrides,
        )

    _append_skill_map_entries(learned, {})

    # Rebuild the section in original order, then append any catch-all extras.
    out = [
        {"category": g["category"], "keywords": by_cat[g["category"].strip().lower()]}
        for g in skills_section
    ]
    for category, keywords in extras:
        if category and keywords:
            out.append({"category": category, "keywords": keywords})
    return out


# --- Cover letter generation ---------------------------------------------------

_COVER_LETTER_SYSTEM_PROMPT = """\
You are a thoughtful career writer helping a real person write a cover letter \
they'd actually be proud to send. It should read like the candidate wrote it \
themselves on a good day - warm, specific, and human - NOT like a template or \
an AI.

You will be given:
1. The candidate's resume as JSON (summary, skills, experience, projects).
2. A structured analysis of the target job description.
3. The company name and role title (may be empty).

Write a cover letter body of 3-4 short paragraphs:
1. Opening: open with a genuine, specific hook - what draws this person to \
THIS role or company, tied to something real in their background. Avoid \
boilerplate; sound like a person, not a form letter.
2. Middle paragraph(s): tell 1-2 brief, concrete stories from the resume that \
map to the job's key needs - a real accomplishment with its actual outcome \
(numbers/tools/results that ALREADY APPEAR in the resume), framed as "here's \
how I'd help you", not just a restatement of bullet points.
3. Closing: a confident, sincere sign-off - genuine enthusiasm for the role \
and a forward-looking note about contributing, without grovelling.

Voice & tone:
- Write in natural first person ("I"), with the warmth and rhythm of real \
human writing. Vary sentence length. It's fine to show a little personality \
and authentic enthusiasm.
- Be specific over generic: name the actual company/role and the actual work, \
not "your esteemed organization" or "a fast-paced environment".
- Confident but not arrogant; concise but not robotic.

Hard rules:
- Every fact, number, tool, employer, or accomplishment mentioned MUST already \
appear in the provided resume JSON. Do NOT invent anything - no fake metrics, \
employers, tools, or experiences.
- Do NOT fabricate company-specific details beyond the company name/role \
given (don't praise products or facts you weren't told).
- BAN these clichés and openers: "I am writing to express my interest", "I am \
excited to apply", "esteemed", "fast-paced environment", "team player", \
"perfect fit", "wealth of experience", "proven track record", "synergy", "I \
believe I would be a great fit". Get to something real instead.
- Do not include a salutation ("Dear ...") or signature ("Sincerely, ...") - \
those are added separately by the template.

Respond with ONLY a JSON object (no markdown, no commentary) with this exact \
shape:
{
  "paragraphs": ["string", "string", ...]
}
"""


def generate_cover_letter(
    master: dict,
    jd_analysis: dict,
    *,
    company: str = "",
    role: str = "",
) -> dict:
    """Generate a cover letter body grounded in the candidate's resume.

    Returns {"paragraphs": [str, ...]}. Raises OllamaError on connection/JSON
    issues.
    """
    # Trim the resume to the fields useful for a cover letter, to keep the
    # prompt focused.
    trimmed_master = {
        "summary": master.get("summary") or "",
        "title_line": master.get("title_line") or "",
        "skills": master.get("skills", []),
        "experience": [
            {
                "company": job.get("company", ""),
                "title": job.get("title", ""),
                "bullets": job.get("bullets", []),
            }
            for job in master.get("experience", [])
        ],
        "projects": [
            {
                "name": proj.get("name", ""),
                "bullets": proj.get("bullets", []),
            }
            for proj in master.get("projects", [])
        ],
    }

    user_prompt = (
        f"Company: {company or '(not specified)'}\n"
        f"Role: {role or '(not specified)'}\n\n"
        "Candidate resume:\n"
        f"{json.dumps(trimmed_master, indent=2)}\n\n"
        "Job description analysis:\n"
        f"{json.dumps(jd_analysis, indent=2)}"
    )

    result = chat_json(_COVER_LETTER_SYSTEM_PROMPT, user_prompt)
    paragraphs = [str(p) for p in result.get("paragraphs", []) or [] if str(p).strip()]

    if not paragraphs:
        raise ValueError("Cover letter generation returned no paragraphs.")

    return {"paragraphs": paragraphs}


# --- Resume bootstrap (extraction from raw resume text) -----------------------

_BOOTSTRAP_SYSTEM_PROMPT = """\
You are a meticulous data-entry assistant. Convert the candidate's raw resume \
text into a structured JSON object that EXACTLY matches the schema below. \
This is EXTRACTION ONLY: copy facts, wording, numbers, and dates from the \
source text. Do not summarize, embellish, invent, infer missing information, \
or add anything not present in the source text.

Schema:
{
  "contact": {
    "name": "string", "email": "string", "phone": "string or null",
    "location": "string or null", "linkedin": "string or null",
    "github": "string or null", "website": "string or null"
  },
  "title_line": "string or null - the tagline under the name, if present",
  "summary": "string or null",
  "skills": [{"category": "string", "keywords": ["string", ...]}],
  "experience": [
    {"company": "string", "title": "string", "location": "string or null",
     "start": "string", "end": "string", "bullets": ["string", ...]}
  ],
  "education": [
    {"institution": "string", "degree": "string", "location": "string or null",
     "start": "string or null", "end": "string or null", "details": ["string", ...]}
  ],
  "projects": [
    {"name": "string", "description": "string or null", "start": "string or null",
     "end": "string or null", "tech": ["string", ...],
     "link": "string or null", "bullets": ["string", ...]}
  ],
  "certifications": ["string", ...],
  "awards": ["string", ...]
}

Rules:
- If a field/section is not present in the source text, use null (for scalar \
fields) or an empty list (for list fields). Never fabricate placeholder values.
- Preserve the original wording of bullets, summary, and skill names verbatim.
- "details" under education can include GPA, honors, coursework, etc. if \
present in the source.
- Respond with ONLY the JSON object - no markdown, no commentary.
"""


def bootstrap_resume_from_text(resume_text: str) -> dict:
    """Extract a structured resume dict from raw resume text via the LLM.

    This is extraction only (no embellishment) - intended as a starting point
    for a `master_resume.yaml` that the user reviews and corrects by hand.
    Raises OllamaError on connection/JSON issues, ValueError if input is empty.
    """
    resume_text = (resume_text or "").strip()
    if not resume_text:
        raise ValueError("Resume text is empty.")

    user_prompt = f"Resume text:\n\"\"\"\n{resume_text}\n\"\"\""
    return chat_json(_BOOTSTRAP_SYSTEM_PROMPT, user_prompt, temperature=0.0)


if __name__ == "__main__":
    # Quick manual check: python -m app.llm
    import sys
    import textwrap

    sample_jd = textwrap.dedent("""
        We are hiring a Data Analyst with 2+ years of experience in Power BI,
        DAX, and SQL. The ideal candidate has experience building dashboards,
        performing data validation, and working with cross-functional teams
        in Finance and Operations. Experience with Python (Pandas) and AWS
        is a plus. Strong communication and stakeholder management skills
        required. Bachelor's degree in a quantitative field preferred.
    """).strip()

    try:
        analysis = analyze_job(sample_jd)
    except (OllamaError, ValueError) as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    print("--- JD analysis ---")
    print(json.dumps(analysis, indent=2))

    from app.config import MASTER_RESUME_PATH
    from app.models import load_resume, resume_to_dict

    master = resume_to_dict(load_resume(MASTER_RESUME_PATH))

    try:
        tailored = tailor_resume(master, analysis)
    except (OllamaError, ValueError) as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    print("\n--- Tailored title_line ---")
    print(tailored["diff"]["title_line"])

    print("\n--- Tailored skills ---")
    print(json.dumps(tailored["diff"]["skills"], indent=2))

    try:
        cover_letter = generate_cover_letter(
            master, analysis, company="Acme Analytics", role="Data Analyst"
        )
    except (OllamaError, ValueError) as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    print("\n--- Cover letter paragraphs ---")
    for p in cover_letter["paragraphs"]:
        print(p)
        print()
