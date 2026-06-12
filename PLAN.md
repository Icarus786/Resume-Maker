# Plan: Local ATS Resume + Cover Letter Tailoring Web App

## Context

You have **Llama 3.1 running locally via Ollama** and want a tool where you keep one
**master resume** in a fixed professional layout, paste in a **job description**, and get
back a **tailored resume PDF** plus a **cover letter PDF** for that job. The tailoring must
surface the right ATS keywords for each posting **without fabricating experience** — the LLM
rewords and reorders what's already true and *proposes* new keywords for you to approve.

Everything runs **offline on your PC**: Python/FastAPI backend, simple browser UI on
`localhost`, Ollama for the model, and a **LaTeX template compiled by MiKTeX** for clean,
ATS-friendly PDF output.

This document also answers your first question — **what format to give your resume in** —
see "Decision: master resume format" below.

> **Implementation note:** This plan is intended to be handed to another model
> (Sonnet) to implement. Sections 0 and 1 were already partially built and
> tested in a prior session — see "Current status" — and should be **kept as a
> head start**. Pick up from where those leave off.

---

## Current status (already built & tested — keep these)

Confirmed on this machine: **Python 3.12.10**, **Ollama reachable**, model
installed as **`Llama3.1:latest`**. **MiKTeX / `pdflatex` is NOT installed yet**
— that is the one remaining prerequisite the user must install.

⚠️ **Gotcha baked in:** Ollama model names are **case-sensitive** when calling the
API, and the installed tag is `Llama3.1:latest` (capital L). All code must
default `OLLAMA_MODEL` to `Llama3.1:latest`, not `llama3.1`. The env-check's
*availability* match is case-insensitive, but the actual API *call* must use the
exact installed name.

Files already created and working:
- `requirements.txt` — fastapi, uvicorn[standard], jinja2, pyyaml, httpx,
  pydantic, python-multipart (all pip-installed and importing).
- `app/__init__.py`
- `app/config.py` — central paths + Ollama/LaTeX settings, env-overridable.
  Already defaults `OLLAMA_MODEL` to `Llama3.1:latest` and exposes
  `OLLAMA_BASE_URL`, `OLLAMA_TEMPERATURE` (0.2), `OLLAMA_TIMEOUT_SECONDS` (300),
  `PDFLATEX_BINARY`, and an `ensure_dirs()` helper. **Reuse this everywhere.**
- `check_env.py` — verifies packages, `pdflatex` on PATH, and Ollama+model.
  Passes for packages and Ollama today; fails on pdflatex until MiKTeX installs.
- `app/models.py` — Pydantic schema (`Contact`, `SkillGroup`, `Experience`,
  `Education`, `Project`, `Resume`) + `load_resume()` (clear errors on bad YAML)
  and `resume_to_dict()`. **This is the canonical data model — build the sample
  YAML and templates against these exact field names.**

Remaining work for the implementer: **Section 1's sample YAML** (model exists,
sample file does not yet) and **Sections 2–8** in full.

Schema field names to render against (from `app/models.py`):
- `contact`: name, email, phone?, location?, linkedin?, github?, website?
- `summary?`
- `skills[]`: {category, items[]}
- `experience[]`: {company, title, location?, start, end, bullets[]}
- `education[]`: {institution, degree, location?, start?, end?, details[]}
- `projects[]`: {name, description?, tech[], link?, bullets[]}

---

## Decision: master resume format (how the app reads your details)

**Give the app your resume as structured YAML/JSON, not a raw PDF/DOCX.**

Reason: reliably parsing layout out of a PDF is fragile and the #1 cause of ATS mistakes.
Instead we **separate content from layout**:

- **Content** → a `master_resume.yaml` file: your name, contact, a list of jobs (each with
  company, title, dates, and bullet points), skills, education, projects. Plain text, easy
  to edit.
- **Layout** → a fixed **LaTeX template** (`resume_template.tex`) that knows how to render
  that YAML into a polished, single-column, ATS-parseable PDF.

So the LLM only ever touches *content* (rewording bullets, ordering skills); the *layout*
never changes and never breaks. You author your master resume once in YAML. The plan
includes a one-time helper to bootstrap that YAML from your existing resume text.

---

## Architecture (offline, all on localhost)

```
Browser UI  ──>  FastAPI backend  ──>  Ollama (Llama 3.1, :11434)
                      │
                      ├─ reads master_resume.yaml
                      ├─ asks LLM to tailor bullets + propose keywords
                      ├─ you approve keywords in UI
                      ├─ renders tailored YAML -> LaTeX -> MiKTeX -> PDF
                      └─ generates cover letter -> LaTeX -> PDF
```

- **LLM runtime:** Ollama at `http://localhost:11434/api/chat`, model `Llama3.1:latest`.
- **PDF engine:** MiKTeX (`pdflatex`), invoked via `subprocess`.
- **Stack:** Python 3.11+, FastAPI + Uvicorn, Jinja2 (to fill the .tex template),
  PyYAML, `httpx` (Ollama calls). Frontend is a single static HTML page + vanilla JS.

---

## Prerequisites (one-time, you install)

1. **Ollama** with the model: `ollama pull llama3.1` (verify `ollama list`).
   _On this machine it's already installed as `Llama3.1:latest`._
2. **MiKTeX** for Windows (https://miktex.org/download) — gives `pdflatex` on PATH.
   First compile may prompt to auto-install LaTeX packages; allow it.
3. **Python 3.11+** (3.12.10 confirmed here).

`python check_env.py` verifies all three before building features.

---

## Build plan — small, independently testable sections

Each section is "bulletproof": it can be built and verified on its own before moving on.

### Section 0 — Project scaffold & environment check  ✅ DONE
- Create folders: `app/` (backend), `app/static/` (UI), `data/` (your YAML),
  `templates/` (LaTeX), `output/` (generated PDFs).
- `requirements.txt`: fastapi, uvicorn, jinja2, pyyaml, httpx.
- `check_env.py`: confirms Ollama reachable, model present, and `pdflatex` on PATH.
- **Verify:** `python check_env.py` prints all-green.

### Section 1 — Master resume data model + sample  🟡 PARTIAL (model done, sample TODO)
- ✅ Pydantic models in `app/models.py` already define the schema and provide
  `load_resume()` / `resume_to_dict()`. **Do not rewrite — build against them.**
- ⬜ **TODO:** create a filled **sample** `data/master_resume.yaml` matching the
  schema field names listed in "Current status", so Sections 2–6 can be built and
  tested before the user's real data is in.
- **Verify:** `python -m app.models` loads the YAML and prints a validated summary
  (the `__main__` block is already wired for this); bad YAML errors clearly.

### Section 2 — LaTeX resume template → PDF (no LLM yet)
- `templates/resume_template.tex`: single-column, ATS-friendly (standard fonts, no
  multi-column tricks, no text-in-images, real selectable text). Jinja2 placeholders.
- `app/render.py`: `render_resume(resume_dict) -> pdf_path` — fills template, runs
  `pdflatex` in `output/`, returns the PDF. Includes LaTeX-escaping of special chars.
- **Verify:** render the sample YAML → open `output/resume.pdf`, confirm clean layout and
  that text is selectable/copy-pasteable (ATS requirement).

### Section 3 — Ollama client + JD analysis
- `app/llm.py`: thin `chat()` wrapper over Ollama with deterministic settings
  (low temperature) and JSON-mode responses.
- `analyze_job(jd_text) -> {hard_keywords[], soft_keywords[], title, must_haves[]}`.
- **Verify:** paste a sample JD, get a sensible structured keyword list back.

### Section 4 — Resume tailoring (reword/reorder + JD skill merging)
- `tailor_resume(master, jd_analysis)`:
  - Reword/reorder existing bullets & skills to mirror JD phrasing **using only facts
    present in the master** (strict prompt: "never invent experience, titles, tools, or
    metrics not in the source" for `experience`/`projects`/`summary`/`title_line`).
  - For `skills`: every hard/soft keyword from the JD analysis that's missing is added
    directly into the best-matching existing skill category (or at most one new category
    if nothing fits), so Core Skills mirrors the JD's required skills.
- A diff structure so the UI can show original vs. tailored skills/summary/title, including
  any new skill category added.
- **Verify:** tailored YAML preserves all `experience`/`projects` facts; review the skills
  diff before downloading and remove anything you don't actually have.

### Section 5 — Cover letter generation
- `templates/cover_letter_template.tex` + `generate_cover_letter(master, jd_analysis,
  company, role)`.
- 3–4 paragraphs, grounded in real resume facts, professional tone, configurable.
- **Verify:** render cover letter PDF; reads naturally, no fabricated claims.

### Section 6 — Web UI (the workflow)
- One page (`app/static/index.html` + `app.js`):
  1. Paste job description (+ optional company/role fields).
  2. **Analyze** → shows detected keywords.
  3. **Tailor** → side-by-side original vs. tailored bullets; checkbox list of
     **proposed keywords to approve**; approved ones get woven in on re-render.
  4. Buttons: **Download Resume PDF**, **Download Cover Letter PDF**.
- FastAPI routes: `/analyze`, `/tailor`, `/render/resume`, `/render/cover-letter`.
- **Verify:** full end-to-end run from browser produces both PDFs in `output/`.

### Section 7 — Bootstrap helper for YOUR real resume (one-time)
- `bootstrap_resume.py`: you paste your current resume text; it asks Llama to convert it
  into the `master_resume.yaml` structure (extraction only — no embellishment), which you
  then **review and correct by hand**. This is how your real data enters the system safely.
- **Verify:** produces valid YAML that renders to a PDF matching your real resume content.

### Section 8 — Polish & safeguards
- "Honesty guard": post-check that flags any tailored bullet containing a number/tool/title
  not found in the master, so nothing fabricated slips through.
- Per-job output folders (`output/<company>-<role>/`) so you keep a history.
- `run.bat` / README with start command: `uvicorn app.main:app --reload`.

---

## Key files to be created

| File | Purpose | Status |
|------|---------|--------|
| `data/master_resume.yaml` | Your single source of truth (content only) | TODO (sample) |
| `templates/resume_template.tex` | Fixed ATS-friendly resume layout | TODO |
| `templates/cover_letter_template.tex` | Cover letter layout | TODO |
| `app/config.py` | Central paths + Ollama/LaTeX settings | ✅ done |
| `app/models.py` | Pydantic schema + YAML loader | ✅ done |
| `app/llm.py` | Ollama client, JD analysis, tailoring, cover letter | TODO |
| `app/render.py` | YAML → LaTeX → pdflatex → PDF | TODO |
| `app/main.py` | FastAPI app + routes | TODO |
| `app/static/index.html`, `app.js` | Browser UI | TODO |
| `check_env.py` | Setup helper | ✅ done |
| `bootstrap_resume.py` | One-time real-resume importer | TODO |

---

## End-to-end verification

1. `python check_env.py` → Ollama, model, and `pdflatex` all OK.
2. Render sample resume (Section 2) → selectable-text PDF, clean layout.
3. `uvicorn app.main:app` → open `http://localhost:8000`.
4. Paste a real JD → Analyze → Tailor → approve a couple keywords → download both PDFs.
5. Open PDFs: confirm tailored resume keeps every fact from master, includes approved
   keywords naturally, and cover letter is grounded and professional.
6. Run an ATS sanity check: copy-paste text out of the resume PDF — it should come out
   clean and in reading order (proves ATS-parseable).

---

## Notes / things to confirm during build
- ATS-friendliness comes from the **template** (single column, standard fonts, selectable
  text, no tables-as-layout, no graphics for text) — kept fixed so it can't regress.
- The LLM **never** changes layout and is constrained to **reword/reorder + propose**, with
  an honesty guard as a backstop, matching your chosen edit scope.
