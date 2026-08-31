"""Deleting a resume must not leave the profile quoting a file that is gone.

`profile_skills.resume_id` and `experiences.resume_id` are ON DELETE SET NULL,
so before this was fixed a deleted resume left behind rows still labelled
"from your resume" whose evidence quoted text from the removed file. The real
profile had one: a Deep Learning skill quoting "CS 231N Convolutional Neural
Networks", a course that appeared in no resume the student still had.
"""

from __future__ import annotations

import uuid

from app.api.routes.resumes import delete_resume
from app.models.resume import Resume
from app.models.user import Experience, ProfileSkill, Skill, StudentProfile, User


def _profile(db) -> StudentProfile:
    user = User(email=f"{uuid.uuid4().hex}@example.edu")
    db.add(user)
    db.flush()
    profile = StudentProfile(user_id=user.id, university="Stanford University")
    db.add(profile)
    db.flush()
    return profile


def _resume(db, profile: StudentProfile) -> Resume:
    resume = Resume(
        user_id=profile.user_id,
        label="Research resume",
        original_filename="research.txt",
        content_type="text/plain",
        storage_path=f"{uuid.uuid4().hex}.txt",
        size_bytes=10,
        checksum=uuid.uuid4().hex,
        parse_status="parsed",
    )
    db.add(resume)
    db.flush()
    return resume


def test_deleting_a_resume_removes_the_skills_it_created(db):
    profile = _profile(db)
    resume = _resume(db, profile)
    skill = Skill(slug=f"deep-learning-{uuid.uuid4().hex[:6]}", label="Deep Learning")
    db.add(skill)
    db.flush()
    db.add(
        ProfileSkill(
            profile_id=profile.id,
            skill_id=skill.id,
            origin="resume",
            resume_id=resume.id,
            evidence="CS 231N Convolutional Neural Networks",
        )
    )
    db.flush()

    delete_resume(resume.id, db=db)

    rows = db.query(ProfileSkill).filter(ProfileSkill.profile_id == profile.id).all()
    assert rows == [], "a skill quoting the deleted resume survived it"


def test_a_skill_the_student_typed_survives_the_resume(db):
    """Only rows the file created are removed; the student's own claims are theirs."""
    profile = _profile(db)
    resume = _resume(db, profile)
    skill = Skill(slug=f"python-{uuid.uuid4().hex[:6]}", label="Python")
    db.add(skill)
    db.flush()
    db.add(ProfileSkill(profile_id=profile.id, skill_id=skill.id, origin="user"))
    db.flush()

    delete_resume(resume.id, db=db)

    rows = db.query(ProfileSkill).filter(ProfileSkill.profile_id == profile.id).all()
    assert len(rows) == 1 and rows[0].origin == "user"


def test_experiences_read_from_the_resume_go_with_it(db):
    profile = _profile(db)
    resume = _resume(db, profile)
    db.add(
        Experience(
            profile_id=profile.id,
            organization="Stanford HCI Group",
            role="Research Assistant",
            origin="resume",
            resume_id=resume.id,
        )
    )
    db.flush()

    delete_resume(resume.id, db=db)

    assert db.query(Experience).filter(Experience.profile_id == profile.id).all() == []
