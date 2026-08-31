"""SQLAlchemy models.

Import order matters: ``user`` defines ``ResearchTopic`` and the ``enum_col``
helper that the other modules build on.
"""

from app.db.base import Base
from app.models.application import (
    Application,
    ApplicationAnswer,
    ApplicationDocument,
    ApplicationEvent,
    ResumeRecommendation,
)
from app.models.change import ChangeKind, OpportunityChange
from app.models.feedback import OpportunityFeedback
from app.models.opportunity import (
    ExtractedField,
    Opportunity,
    OpportunityMatch,
    OpportunitySource,
    OpportunityTopic,
    Requirement,
    SourceDocument,
)
from app.models.ops import (
    AgentRun,
    DataProvenance,
    Reminder,
    SavedSearch,
    SearchRun,
)
from app.models.research import (
    Faculty,
    FacultyTopic,
    Lab,
    LabSignal,
    ResearchEvidence,
)
from app.models.resume import Resume, ResumeHighlight
from app.models.user import (
    Coursework,
    Experience,
    ProfileResearchInterest,
    ProfileSkill,
    ResearchTopic,
    Skill,
    StudentProfile,
    User,
)

__all__ = [
    "AgentRun",
    "Application",
    "ApplicationAnswer",
    "ApplicationDocument",
    "ApplicationEvent",
    "Base",
    "ChangeKind",
    "Coursework",
    "DataProvenance",
    "Experience",
    "ExtractedField",
    "Faculty",
    "FacultyTopic",
    "Lab",
    "LabSignal",
    "Opportunity",
    "OpportunityChange",
    "OpportunityFeedback",
    "OpportunityMatch",
    "OpportunitySource",
    "OpportunityTopic",
    "ProfileResearchInterest",
    "ProfileSkill",
    "Reminder",
    "Requirement",
    "ResearchEvidence",
    "ResearchTopic",
    "Resume",
    "ResumeHighlight",
    "ResumeRecommendation",
    "SavedSearch",
    "SearchRun",
    "Skill",
    "SourceDocument",
    "StudentProfile",
    "User",
]
