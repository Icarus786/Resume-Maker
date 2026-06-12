"""Pydantic schema for the master resume + YAML loading/validation.

The resume is stored as content-only YAML (see data/master_resume.yaml). The
layout lives entirely in the LaTeX template, so these models describe *what* is
on the resume, never *how* it looks.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, ValidationError


class Contact(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    location: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    website: Optional[str] = None


class SkillGroup(BaseModel):
    """A labelled cluster of skills, e.g. 'Languages: Python, Go, SQL'."""
    category: str
    # Named `keywords` (not `items`) because dicts already have an `.items()`
    # method, which shadows a dict key named `items` during Jinja2 templating.
    keywords: list[str] = Field(default_factory=list)


class Experience(BaseModel):
    company: str
    title: str
    location: Optional[str] = None
    start: str  # free text, e.g. "Jan 2022"
    end: str    # free text, e.g. "Present"
    bullets: list[str] = Field(default_factory=list)


class Education(BaseModel):
    institution: str
    degree: str
    location: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    details: list[str] = Field(default_factory=list)


class Project(BaseModel):
    name: str
    description: Optional[str] = None
    start: Optional[str] = None  # free text, e.g. "Jan 2024"
    end: Optional[str] = None    # free text, e.g. "Aug 2024"
    tech: list[str] = Field(default_factory=list)
    link: Optional[str] = None
    bullets: list[str] = Field(default_factory=list)


class Resume(BaseModel):
    contact: Contact
    title_line: Optional[str] = None
    summary: Optional[str] = None
    core_competencies: list[SkillGroup] = Field(default_factory=list)
    skills: list[SkillGroup] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    awards: list[str] = Field(default_factory=list)
    hobbies: list[str] = Field(default_factory=list)


def load_resume(path: str | Path) -> Resume:
    """Load and validate a master resume YAML file.

    Raises a clear ValueError on malformed YAML or schema violations so callers
    (CLI, API) can surface a readable message.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Master resume not found: {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Could not parse YAML in {path}:\n{exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level.")

    try:
        return Resume.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"Resume in {path} failed validation:\n{exc}") from exc


def resume_to_dict(resume: Resume) -> dict:
    """Plain dict for templating / LLM round-trips."""
    return resume.model_dump()


if __name__ == "__main__":
    # Quick manual check: python -m app.models
    import sys

    from app.config import MASTER_RESUME_PATH

    try:
        r = load_resume(MASTER_RESUME_PATH)
    except (ValueError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)
    print(f"Loaded resume for: {r.contact.name}")
    print(f"  {len(r.skills)} skill groups, {len(r.experience)} jobs, "
          f"{len(r.education)} education, {len(r.projects)} projects")
