/**
 * Shared reading of a research lead.
 *
 * A lead is judged on three things — what the lab is working on *now*, whether
 * undergraduates are visibly part of it, and whether any of that touches the
 * student. Those readings are made here, once, so the browse card and the lab
 * profile can never disagree about what the same record says.
 */

import type {
  LabSignalItem,
  LeadState,
  ProfileInterestItem,
  ResearchEvidenceItem,
  ResearchLead,
  StudentProfile,
} from "@/lib/types";

export const EVIDENCE_KIND_LABEL: Record<ResearchEvidenceItem["kind"], string> = {
  publication: "Publication",
  project: "Project",
  news: "News",
  grant: "Grant",
  course: "Course",
  talk: "Talk",
  student_project: "Student project",
};

/** Work from the current year or the two before it still counts as current. */
export const RECENCY_WINDOW_YEARS = 2;

export function isRecent(year: number | null, thisYear: number): boolean {
  return year !== null && year >= thisYear - RECENCY_WINDOW_YEARS;
}

/* ------------------------------------------------------------------ names */

export function labHeading(lead: ResearchLead): string {
  return lead.lab?.name ?? lead.faculty.name;
}

/** The line under the heading: never repeats whatever the heading already said. */
export function labSubheading(lead: ResearchLead): string {
  const f = lead.faculty;
  const parts = lead.lab ? [f.name, f.department] : [f.title, f.department];
  const kept = parts.filter((p): p is string => Boolean(p && p.trim()));
  return kept.length ? kept.join(" · ") : f.university;
}

/* --------------------------------------------------------------- signals */

export const SIGNAL_KINDS: LabSignalItem["kind"][] = [
  "undergrad_presence",
  "recruiting",
  "activity",
];

export const SIGNAL_KIND_LABEL: Record<LabSignalItem["kind"], string> = {
  undergrad_presence: "Undergraduates in the lab",
  recruiting: "Recruiting statement",
  activity: "Recent activity",
};

/**
 * The one signal a card has room for. Undergraduate presence outranks a
 * recruiting line, because a lab that already has undergrads is the stronger
 * fact even when a recruiting page exists; an evidenced signal always outranks
 * an unknown one.
 */
export function primarySignal(signals: LabSignalItem[]): LabSignalItem | null {
  const known = (kind: LabSignalItem["kind"]) =>
    signals.find((s) => s.kind === kind && s.certainty !== "unknown");
  return (
    known("undergrad_presence") ??
    known("recruiting") ??
    signals.find((s) => s.kind === "undergrad_presence") ??
    signals[0] ??
    null
  );
}

/* ------------------------------------------------------------- searching */

export function leadSearchText(lead: ResearchLead): string {
  const f = lead.faculty;
  return [
    f.name,
    f.title,
    f.department,
    lead.lab?.name,
    ...f.current_direction,
    ...lead.topics.map((t) => t.label),
    ...lead.overlap.map((o) => o.topic),
    lead.latest_evidence?.title,
  ]
    .filter((p): p is string => Boolean(p))
    .join(" ")
    .toLowerCase();
}

/* --------------------------------------------------------------- sorting */

export type LeadSort = "match" | "recent" | "opening";

export const SORT_OPTIONS: { value: LeadSort; label: string }[] = [
  { value: "match", label: "Match" },
  { value: "recent", label: "Recently active" },
  { value: "opening", label: "Opening first" },
];

export function isLeadSort(v: string): v is LeadSort {
  return v === "match" || v === "recent" || v === "opening";
}

const STATE_RANK: Record<LeadState, number> = { opening: 0, outreach: 1, watch: 2, unknown: 3 };

const byMatch = (a: ResearchLead, b: ResearchLead) =>
  (b.fit_score ?? -1) - (a.fit_score ?? -1);

const byRecent = (a: ResearchLead, b: ResearchLead) =>
  (b.faculty.last_evidence_year ?? -1) - (a.faculty.last_evidence_year ?? -1);

export function compareLeads(sort: LeadSort) {
  return (a: ResearchLead, b: ResearchLead): number => {
    if (sort === "recent") return byRecent(a, b) || byMatch(a, b);
    if (sort === "opening") {
      return STATE_RANK[a.lead_state] - STATE_RANK[b.lead_state] || byMatch(a, b);
    }
    return byMatch(a, b) || byRecent(a, b);
  };
}

export function isLeadState(v: string): v is LeadState {
  return v === "opening" || v === "outreach" || v === "watch" || v === "unknown";
}

/* ------------------------------------------------------ topic matching */

export function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/**
 * Whole-segment slug overlap: "llm-agents" matches "agents", but "ai" does not
 * match "chair". Substring matching would invent overlaps the student never
 * claimed, which is the one thing this product must not do.
 */
export function slugsOverlap(a: string, b: string): boolean {
  if (!a || !b) return false;
  if (a === b) return true;
  return `-${a}-`.includes(`-${b}-`) || `-${b}-`.includes(`-${a}-`);
}

export function interestSlug(interest: ProfileInterestItem): string {
  return interest.topic_slug ?? slugify(interest.label);
}

export interface BackgroundPoint {
  label: string;
  detail: string | null;
  origin: "interest" | "coursework" | "experience" | "skill";
}

/**
 * The parts of the student's own profile that touch this lab's topics.
 *
 * Only records the student actually entered are returned — nothing is
 * generated, softened or embellished, because these points are what they will
 * say about themselves in an email.
 */
export function matchingBackground(
  profile: StudentProfile | null,
  topicSlugs: string[],
): BackgroundPoint[] {
  if (!profile) return [];
  const wanted = topicSlugs.filter(Boolean);
  const hits = (slugs: string[]) =>
    slugs.some((s) => wanted.some((w) => slugsOverlap(s, w)));

  const points: BackgroundPoint[] = [];

  for (const interest of profile.interests) {
    if (hits([interestSlug(interest)])) {
      points.push({ label: interest.label, detail: interest.note, origin: "interest" });
    }
  }
  for (const course of profile.coursework) {
    if (hits(course.topics.map(slugify))) {
      points.push({
        label: [course.code, course.title].filter(Boolean).join(" — "),
        detail: course.term,
        origin: "coursework",
      });
    }
  }
  for (const exp of profile.experiences) {
    if (hits(exp.skills.map(slugify))) {
      points.push({
        label: `${exp.role} · ${exp.organization}`,
        detail: exp.summary,
        origin: "experience",
      });
    }
  }
  for (const skill of profile.skills) {
    if (hits([skill.slug])) {
      points.push({ label: skill.label, detail: skill.evidence, origin: "skill" });
    }
  }
  return points;
}
