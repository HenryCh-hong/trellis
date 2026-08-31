"""Resume upload, parsing and protected download.

Uploaded files are written under ``settings.resume_dir`` (outside any static or
web-served directory) and are only reachable through :func:`download_resume`.
The stored filename is derived from a UUID, never from user input, so a
crafted filename cannot escape the directory.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import serializers as ser
from app.api.deps import current_profile_optional, current_user, get_session
from app.core.config import get_settings
from app.core.security import sha256_b64
from app.models.resume import Resume, ResumeHighlight
from app.models.user import StudentProfile, User
from app.schemas import entities as E
from app.services import resume_parser

router = APIRouter(tags=["resumes"])

ALLOWED_SUFFIXES = {".pdf", ".txt", ".md"}
ALLOWED_TYPES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "application/octet-stream",
}


@router.get("/resumes", response_model=list[E.ResumeItem])
def list_resumes(db: Session = Depends(get_session)) -> list[E.ResumeItem]:
    rows = db.scalars(select(Resume).order_by(Resume.created_at.desc())).all()
    return [ser.resume_item(db, r) for r in rows]


@router.post("/resumes", response_model=E.ResumeItem, status_code=201)
async def upload_resume(
    file: UploadFile = File(...),
    label: str = Form(default=""),
    db: Session = Depends(get_session),
    user: User = Depends(current_user),
    profile: StudentProfile | None = Depends(current_profile_optional),
) -> E.ResumeItem:
    settings = get_settings()
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail="Upload a PDF, .txt or .md file. Other formats are not parsed.",
        )
    if file.content_type and file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported content type {file.content_type}.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="That file was empty.")
    if len(data) > settings.max_resume_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"That file is larger than {settings.max_resume_bytes // (1024 * 1024)}MB.",
        )

    # Filename comes from us, not from the upload.
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    target = settings.resume_dir / stored_name
    target.write_bytes(data)
    target.chmod(0o600)

    resume = Resume(
        user_id=user.id,
        label=(label.strip() or Path(file.filename or "resume").stem)[:120],
        original_filename=(file.filename or stored_name)[:400],
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(data),
        storage_path=stored_name,
        checksum=sha256_b64(data),
        is_default=db.scalar(select(Resume.id).limit(1)) is None,
    )
    db.add(resume)
    db.flush()

    parsed = resume_parser.parse_resume(target, content_type=resume.content_type)
    resume.parse_status = parsed.parse_status
    resume.parse_error = parsed.parse_error
    resume.parsed_at = datetime.now(UTC)
    resume.page_count = parsed.page_count
    resume.text = parsed.text
    resume.detected_skills = resume_parser.detect_skills(parsed.text)
    resume.detected_topics = resume_parser.detect_topics(parsed.text)
    resume.stats = dict(parsed.stats or {})

    for index, highlight in enumerate(resume_parser.extract_highlights(parsed)):
        db.add(
            ResumeHighlight(
                resume_id=resume.id,
                section=highlight.section,
                text=highlight.text,
                line_index=index,
                skills=list(highlight.skills),
                topics=list(highlight.topics),
            )
        )

    if profile is not None and parsed.parse_status == "parsed":
        _merge_profile_evidence(db, profile, resume, parsed)

    db.flush()
    db.refresh(resume)
    return ser.resume_item(db, resume)


def _merge_profile_evidence(db: Session, profile: StudentProfile, resume: Resume, parsed) -> None:
    """Add skills the resume actually evidences — never invent, never overwrite."""
    from app.models.user import ProfileSkill, Skill

    have = {ps.skill.slug for ps in profile.skills if ps.skill is not None}
    evidence = resume_parser.detect_skill_evidence(parsed.text)
    for slug, snippet in evidence.items():
        if slug in have:
            continue
        skill = db.scalars(select(Skill).where(Skill.slug == slug)).first()
        if skill is None:
            continue
        db.add(
            ProfileSkill(
                profile_id=profile.id,
                skill_id=skill.id,
                origin="resume",
                evidence=snippet[:500],
                resume_id=resume.id,
            )
        )
        have.add(slug)


@router.get("/resumes/{resume_id}", response_model=E.ResumeDetail)
def get_resume(resume_id: uuid.UUID, db: Session = Depends(get_session)) -> E.ResumeDetail:
    resume = db.get(Resume, resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found.")
    base = ser.resume_item(db, resume)
    return E.ResumeDetail(
        **base.model_dump(),
        text_preview=(resume.text or "")[:4000] or None,
        highlights=[
            E.ResumeHighlightItem(
                id=h.id,
                section=h.section,
                text=h.text,
                skills=list(h.skills or []),
                topics=list(h.topics or []),
            )
            for h in resume.highlights
        ],
        stats=dict(resume.stats or {}),
    )


@router.get("/resumes/{resume_id}/file")
def download_resume(resume_id: uuid.UUID, db: Session = Depends(get_session)) -> FileResponse:
    resume = db.get(Resume, resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found.")
    settings = get_settings()
    path = (settings.resume_dir / resume.storage_path).resolve()
    # Defence in depth: the stored name is ours, but re-check containment anyway.
    if not str(path).startswith(str(settings.resume_dir.resolve())) or not path.exists():
        raise HTTPException(status_code=404, detail="That file is no longer on disk.")
    return FileResponse(
        path, media_type=resume.content_type, filename=resume.original_filename
    )


@router.post("/resumes/{resume_id}/default", response_model=E.ResumeItem)
def set_default(resume_id: uuid.UUID, db: Session = Depends(get_session)) -> E.ResumeItem:
    resume = db.get(Resume, resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found.")
    for row in db.scalars(select(Resume)):
        row.is_default = row.id == resume.id
    db.flush()
    return ser.resume_item(db, resume)


@router.delete("/resumes/{resume_id}", status_code=204)
def delete_resume(resume_id: uuid.UUID, db: Session = Depends(get_session)) -> None:
    resume = db.get(Resume, resume_id)
    if resume is None:
        return
    path = get_settings().resume_dir / resume.storage_path
    path.unlink(missing_ok=True)
    db.delete(resume)
    db.flush()
