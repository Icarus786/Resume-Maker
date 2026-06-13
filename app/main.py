"""FastAPI app: ties together JD analysis, tailoring, and PDF rendering.

Routes:
  GET  /                      -> serves the single-page UI
  GET  /api/master-resume     -> the master resume (for the UI to display)
  POST /api/analyze           -> analyze a job description
  POST /api/tailor            -> tailor the master resume against a JD analysis
  POST /api/render/resume     -> render a (tailored) resume to PDF
  POST /api/render/cover-letter -> generate + render a cover letter PDF
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import MASTER_RESUME_PATH, OUTPUT_DIR, STATIC_DIR, ensure_dirs
from app.honesty_guard import check_resume
from app.llm import (
    OllamaError,
    add_skills_to_resume,
    analyze_job,
    generate_cover_letter,
    tailor_resume,
)
from app.models import load_resume, resume_to_dict
from app.render import LatexCompileError, render_cover_letter, render_resume

app = FastAPI(title="Resume Maker")


@app.on_event("startup")
def _startup() -> None:
    ensure_dirs()


# --- Request/response models --------------------------------------------------

class AnalyzeRequest(BaseModel):
    jd_text: str


class TailorRequest(BaseModel):
    jd_analysis: dict
    category_overrides: dict[str, str] = Field(default_factory=dict)
    company: str = ""
    role: str = ""


class AddSkillsRequest(BaseModel):
    skills_section: list[dict] = Field(default_factory=list)
    skill_names: list[str] = Field(default_factory=list)


class RenderResumeRequest(BaseModel):
    resume: dict
    company: str = ""
    role: str = ""
    jd_analysis: dict = Field(default_factory=dict)


class CoverLetterRequest(BaseModel):
    jd_analysis: dict
    company: str = ""
    role: str = ""
    # The tailored resume (reworded bullets) to ground the letter in. Falls
    # back to the master resume when omitted.
    resume: dict = Field(default_factory=dict)


class RenderCoverLetterRequest(BaseModel):
    jd_analysis: dict
    company: str = ""
    role: str = ""
    hiring_manager: str = ""
    subject: str = ""  # full "Re:" line; overrides the default when provided
    paragraphs: list[str] = Field(default_factory=list)


# --- Helpers --------------------------------------------------------------------

def _slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "job"


def _job_output_dir(company: str, role: str) -> Path:
    """Per-job output folder, e.g. output/acme-corp_data-analyst/."""
    company_slug = _slugify(company) if company else ""
    role_slug = _slugify(role) if role else ""
    if company_slug and role_slug:
        name = f"{company_slug}_{role_slug}"
    else:
        name = company_slug or role_slug or "job"
    return OUTPUT_DIR / name


def _resolve_company(company: str, jd_analysis: dict) -> str:
    """Use the explicit `company`, falling back to the JD-detected company name."""
    company = (company or "").strip()
    if company:
        return company
    return str((jd_analysis or {}).get("company_name", "") or "").strip()


def _get_master_resume_dict() -> dict:
    try:
        resume = load_resume(MASTER_RESUME_PATH)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Master resume not found at {MASTER_RESUME_PATH}. "
                   f"Create it first (see PLAN.md Section 1 / 7).",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return resume_to_dict(resume)


# --- Routes -----------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="UI not built yet (app/static/index.html missing).")
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.get("/api/master-resume")
def get_master_resume() -> dict:
    return _get_master_resume_dict()


@app.post("/api/analyze")
def api_analyze(req: AnalyzeRequest) -> dict:
    try:
        return analyze_job(req.jd_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OllamaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/tailor")
def api_tailor(req: TailorRequest) -> dict:
    master = _get_master_resume_dict()
    try:
        result = tailor_resume(master, req.jd_analysis, category_overrides=req.category_overrides)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"Tailoring failed validation: {exc}") from exc
    except OllamaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if "needs_categorization" in result:
        return result

    result["honesty_warnings"] = check_resume(master, result["tailored_resume"])
    # NOTE: the cover letter is intentionally NOT generated here. The frontend
    # shows the tailored resume immediately, then requests /api/cover-letter
    # separately so the (slow) cover-letter LLM call runs in the background
    # without making the user wait to see their resume.
    return result


@app.post("/api/add-skills")
def api_add_skills(req: AddSkillsRequest) -> dict:
    """Insert user-confirmed skills into the tailored resume's skills section.

    Used when the user opts into crucial JD skills the resume lacked (the
    suggested-skills checklist). Returns the updated skills section. Fast: no
    reword/bullet/gap/cover-letter LLM calls - only routing/auto-categorize.
    """
    try:
        skills = add_skills_to_resume(req.skills_section, req.skill_names)
    except OllamaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"skills": skills}


@app.post("/api/render/resume")
def api_render_resume(req: RenderResumeRequest):
    resume = req.resume

    company = _resolve_company(req.company, req.jd_analysis)
    out_dir = _job_output_dir(company, req.role)
    try:
        pdf_path = render_resume(resume, job_name="resume", out_dir=out_dir)
    except LatexCompileError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename="resume.pdf",
    )


@app.post("/api/cover-letter")
def api_cover_letter(req: CoverLetterRequest) -> dict:
    """Generate cover letter text for preview (no PDF).

    Grounds the letter in the tailored `resume` from the request when present
    (so it reflects the reworded bullets), falling back to the master resume.
    """
    source = req.resume if req.resume else _get_master_resume_dict()
    company = _resolve_company(req.company, req.jd_analysis)

    try:
        cover_letter = generate_cover_letter(
            source, req.jd_analysis, company=company, role=req.role
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except OllamaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "paragraphs": cover_letter["paragraphs"],
        "company": company,
        "role": req.role,
    }


@app.post("/api/render/cover-letter")
def api_render_cover_letter(req: RenderCoverLetterRequest):
    master = _get_master_resume_dict()
    company = _resolve_company(req.company, req.jd_analysis)

    paragraphs = [p for p in req.paragraphs if str(p).strip()]
    if not paragraphs:
        try:
            cover_letter = generate_cover_letter(
                master, req.jd_analysis, company=company, role=req.role
            )
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except OllamaError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        paragraphs = cover_letter["paragraphs"]

    context = {
        "contact": master["contact"],
        "date": date.today().strftime("%d %B %Y").lstrip("0"),
        "company": company,
        "role": req.role,
        "hiring_manager": req.hiring_manager,
        "subject": req.subject.strip(),
        "paragraphs": paragraphs,
    }

    out_dir = _job_output_dir(company, req.role)
    try:
        pdf_path = render_cover_letter(context, job_name="cover_letter", out_dir=out_dir)
    except LatexCompileError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename="cover_letter.pdf",
    )


# Mount static assets (CSS/JS) under /static, after API routes are defined.
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
