"""Attach canonical topics to faculty, derived from what they actually publish.

Faculty arrived carrying Stanford's department area names ("Artificial
Intelligence") plus free-text phrases from their own pages. Neither matches the
canonical ontology, so a student whose interest is `llm-agents` never matched a
lab that plainly works on LLM agents — and every explanation collapsed to the
one broad area every lab shares.

This derives leaf topics from each lab's current direction and recent evidence
and attaches them with origin='evidence', which is also the origin the research
scorer weights more heavily.

    python -m scripts.backfill_faculty_topics          # report
    python -m scripts.backfill_faculty_topics --apply
"""

from __future__ import annotations

import sys
from collections import Counter

from sqlalchemy import select

from app.db.session import session_scope
from app.models.research import Faculty, FacultyTopic
from app.models.user import ResearchTopic
from app.services import taxonomy


def main() -> int:
    apply = "--apply" in sys.argv
    added = Counter()
    with session_scope() as db:
        topics = {t.slug: t for t in db.scalars(select(ResearchTopic))}
        canonical = set(taxonomy.topic_index())

        for faculty in db.scalars(select(Faculty)):
            have = {ft.topic.slug for ft in faculty.topics if ft.topic is not None}

            # Weight the lab's own words and its recent output; both describe
            # what it does now far better than a department label.
            blob = " ".join(
                [
                    " ".join(faculty.current_direction or []),
                    " ".join(f"{e.title} {e.summary or ''}" for e in faculty.evidence[:12]),
                    " ".join(faculty.research_areas or []),
                ]
            )
            derived = {
                slug for slug, weight in taxonomy.match_topics(blob) if slug in canonical and weight > 0
            }
            for phrase in faculty.current_direction or []:
                derived |= {s for s, _ in taxonomy.match_topics(phrase) if s in canonical}

            new = derived - have
            if not new:
                continue
            added[faculty.slug] = len(new)
            if not apply:
                continue
            for slug in sorted(new):
                topic = topics.get(slug)
                if topic is None:
                    definition = taxonomy.topic_index().get(slug)
                    topic = ResearchTopic(
                        slug=slug,
                        label=definition.label if definition else taxonomy.humanise_slug(slug),
                        aliases=list(definition.aliases) if definition else [],
                    )
                    db.add(topic)
                    db.flush()
                    topics[slug] = topic
                db.add(
                    FacultyTopic(
                        faculty_id=faculty.id,
                        topic_id=topic.id,
                        weight=1.0,
                        origin="evidence",
                    )
                )

    total = sum(added.values())
    print(f"{len(added)} faculty gain {total} canonical topics")
    for slug, n in added.most_common(8):
        print(f"  {slug:28s} +{n}")
    if not apply:
        print("\n(report only — pass --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
