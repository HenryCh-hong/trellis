/**
 * API contract.
 *
 * Mirrors `apps/api/app/schemas`. Kept hand-written rather than generated so
 * the field names read the way the UI thinks about them, and so a backend
 * rename shows up as a type error here instead of a silent `undefined`.
 */

export type Certainty = "verified" | "likely" | "inferred" | "unknown";

export type OpportunityType =
  | "on_campus"
  | "part_time"
  | "research_opening"
  | "research_outreach";

export type OpportunityStatus =
  | "new"
  | "saved"
  | "preparing"
  | "ready_to_apply"
  | "applying"
  | "submitted"
  | "interview"
  | "offer"
  | "rejected"
  | "archived";

export type DeadlineType = "hard" | "rolling" | "unknown";

/**
 * The RECORDED lifecycle of a deadline, as opposed to `DeadlineType`, which is
 * only what the posting said. "expired" is a state the backend wrote down on a
 * particular day and logged as a change — not an adjective computed on read,
 * which is why it can be trusted to hide a row.
 */
export type DeadlineState = "hard" | "rolling" | "unknown" | "expired";

/** Whether the posting is still on the source it came from. Never deleted. */
export type SourceStatus = "live" | "gone";

export type Urgency =
  | "overdue"
  | "urgent"
  | "soon"
  | "later"
  | "rolling"
  | "unknown";

export type EligibilityState =
  | "eligible"
  | "likely_eligible"
  | "unclear"
  | "ineligible";

export type RequirementKind = "required" | "preferred" | "inferred";
export type RequirementMatchState = "matched" | "partial" | "missing" | "unknown";
/** Four states, in descending order of evidence. "unknown" is a conclusion
 *  ("we read the pages and still cannot say"), never a placeholder. */
export type LeadState = "opening" | "outreach" | "watch" | "unknown";
/** Which side of the discovery confidence gate a row is on. */
export type ConfidenceState = "ok" | "held";
export type Recommendation = "apply" | "strong_apply" | "consider" | "skip" | "reach_out";

/**
 * What you said about one opportunity. Deliberately four verbs, not a rating:
 * every one of them is reversible and every one applies to that row alone.
 */
export type FeedbackSignal =
  | "interested"
  | "not_relevant"
  | "already_applied"
  | "hidden";

/** Why something was not relevant. Recorded for analysis; never a filter. */
export type FeedbackReason =
  | "wrong_topic"
  | "wrong_job_type"
  | "too_far"
  | "not_qualified"
  | "not_interested";

export interface OpportunityFeedback {
  signal: FeedbackSignal;
  /** Only ever set alongside "not_relevant" — the API rejects it elsewhere. */
  reason: FeedbackReason | null;
  note: string | null;
  created_at: string;
}
export type ExtractionMethod = "source" | "regex" | "heuristic" | "llm" | "user";

export interface EvidencedField<T = unknown> {
  value: T | null;
  confidence: number;
  certainty: Certainty;
  method: ExtractionMethod;
  source_text: string | null;
  source_url: string | null;
}

export interface TopicRef {
  slug: string;
  label: string;
  weight?: number;
  origin?: "directory" | "evidence";
}

export interface SourceRef {
  slug: string;
  name: string;
  kind: string;
  base_url: string | null;
  requires_auth: boolean;
  is_public: boolean;
  is_mocked: boolean;
}

export interface ScoreComponent {
  key: string;
  label: string;
  score: number;
  weight: number;
  weighted: number;
  reason: string;
  detail?: string[];
}

export interface MatchDetail {
  fit_score: number;
  confidence: number;
  model: string;
  breakdown: ScoreComponent[];
  strengths: string[];
  gaps: string[];
  explanation: string | null;
  why_interesting: string | null;
  recommendation: Recommendation | null;
  recommended_resume_id: string | null;
  computed_at: string | null;
}

export interface Requirement {
  id: string;
  text: string;
  kind: RequirementKind;
  category: string | null;
  source_text: string | null;
  source_url: string | null;
  confidence: number;
  match_state: RequirementMatchState;
  match_reason: string | null;
}

export interface OpportunityListItem {
  id: string;
  title: string;
  type: OpportunityType;
  status: OpportunityStatus;
  organization: string | null;
  department: string | null;
  lab_name: string | null;
  pi_name: string | null;
  source: SourceRef | null;
  source_url: string | null;
  location: string | null;
  pay_text: string | null;
  hours_per_week: number | null;
  hours_note: string | null;
  deadline: string | null;
  deadline_type: DeadlineType;
  deadline_state: DeadlineState;
  deadline_certainty: Certainty;
  days_until_deadline: number | null;
  urgency: Urgency;
  eligibility: EligibilityState;
  fit_score: number | null;
  fit_confidence: number | null;
  recommendation: Recommendation | null;
  lead_state: LeadState | null;
  topics: TopicRef[];
  first_seen_at: string | null;
  last_checked_at: string | null;
  source_status: SourceStatus;
  /** When `source_status` last changed — i.e. when we looked and it was gone. */
  source_status_at: string | null;
  is_new: boolean;
  has_application: boolean;
  application_id: string | null;
  has_reminder: boolean;
  /** Touches something you said you care about. */
  matches_interests: boolean;
  /** Why, in your own words — so the filter can be interrogated. */
  relevance_reason: string | null;
  /**
   * "held" means so little came off the page that recommending it would be a
   * guess. The row is kept in full and reachable, never deleted.
   */
  confidence_state: ConfidenceState;
  /** What was missing, in one sentence. Only ever set on a held row. */
  confidence_reason: string | null;
  /** Your own signal on this row, or null when you have said nothing. */
  feedback: OpportunityFeedback | null;
}

export interface ResearchEvidenceItem {
  id: string;
  kind: "publication" | "project" | "news" | "grant" | "course" | "talk" | "student_project";
  title: string;
  summary: string | null;
  year: number | null;
  url: string | null;
  venue: string | null;
  authors: string[];
}

export interface LabSignalItem {
  kind: "undergrad_presence" | "recruiting" | "activity";
  label: string;
  certainty: Certainty;
  statement: string | null;
  source_url: string | null;
  note: string | null;
}

export interface FacultyRef {
  id: string;
  slug: string;
  name: string;
  title: string | null;
  department: string | null;
  university: string;
  faculty_url: string | null;
  email: string | null;
  email_certainty: Certainty;
  email_source_url: string | null;
  current_direction: string[];
  current_direction_basis: string | null;
  current_direction_certainty: Certainty;
  last_evidence_year: number | null;
  evidence_count: number;
  is_active: boolean;
  source_urls: string[];
}

export interface LabRef {
  id: string;
  name: string;
  slug: string;
  url: string | null;
  department: string | null;
  description: string | null;
  news_url: string | null;
  people_url: string | null;
  join_url: string | null;
}

export interface TopicOverlap {
  topic: string;
  why: string;
  evidence_year: number | null;
  evidence_title: string | null;
  evidence_url: string | null;
}

/** An interest the student named that this lab's recent work demonstrably touches. */
export interface FitOverlapItem {
  label: string;
  kind: "interest" | "keyword";
  /** A whole sentence citing the dated artefact it was read from. */
  evidence: string;
  source_url: string | null;
}

/**
 * Something the student already has. Only ever a profile row or a line of a
 * resume they uploaded — never a claim assembled on their behalf.
 */
export interface FitBackgroundItem {
  label: string;
  kind: "resume_line" | "coursework" | "experience" | "skill";
  detail: string | null;
  /** The uploaded resume this was read from. Always set when `verbatim`. */
  resume: string | null;
  /** `detail` is the student's own words, character for character. */
  verbatim: boolean;
}

export interface FitGapItem {
  label: string;
  /** True only for a stated hard requirement the student does not meet. */
  blocking: boolean;
  note: string;
}

export interface FitBreakdown {
  strong_overlap: FitOverlapItem[];
  relevant_background: FitBackgroundItem[];
  potential_gaps: FitGapItem[];
  resumes_read: string[];
  /** Set when there was no readable resume, so a short list is never silent. */
  background_note: string | null;
}

/** One specific, sourced reason a lead is in the state it is in. */
export interface LeadStateSignal {
  key: string;
  label: string;
  certainty: Certainty;
  source_url: string | null;
  detail: string | null;
}

export interface DirectionEvidence {
  id: string;
  year: number | null;
  kind: ResearchEvidenceItem["kind"];
  title: string;
  url: string | null;
  /** Which words this item and the direction actually share. Derived, never written. */
  why: string;
}

/**
 * A current direction and the recent work backing it. A direction with no
 * surviving supporting evidence is absent from the list, never present-and-empty.
 */
export interface DirectionClaim {
  direction: string;
  certainty: Certainty;
  evidence: DirectionEvidence[];
}

/** Null when no real timing signal was found. The UI says so rather than inventing one. */
export interface WhyNow {
  statement: string;
  evidence_ids: string[];
  certainty: Certainty;
}

export interface ResearchContext {
  faculty: FacultyRef;
  lab: LabRef | null;
  lead_state: LeadState;
  lead_state_signals: LeadStateSignal[];
  directions: DirectionClaim[];
  why_now: WhyNow | null;
  evidence: ResearchEvidenceItem[];
  signals: LabSignalItem[];
  topics: TopicRef[];
  overlap: TopicOverlap[];
  /** Null when there is no student profile to compare against. */
  fit: FitBreakdown | null;
  suggested_next_step: string | null;
  opening_statement: string | null;
  opening_source_url: string | null;
}

export interface ResumeRecommendationItem {
  resume_id: string;
  resume_label: string;
  score: number;
  rank: number;
  matched_strengths: string[];
  weak_or_missing: string[];
  emphasize: { text: string; why: string }[];
  rationale: string | null;
}

export interface OpportunityDetail extends OpportunityListItem {
  description: string | null;
  application_method: string | null;
  application_url: string | null;
  contact_name: string | null;
  contact_email: string | null;
  requirements: Requirement[];
  preferred: Requirement[];
  inferred: Requirement[];
  documents_required: string[];
  skills: string[];
  eligibility_reasons: string[];
  extraction_confidence: number;
  match: MatchDetail | null;
  fields: Record<string, EvidencedField>;
  research: ResearchContext | null;
  resume_recommendations: ResumeRecommendationItem[];
  /** "Can I apply right now?" — the same computation the kit page renders. */
  readiness: ApplicationReadiness;
  notes: string | null;
}

/* ------------------------------------------------------------------ research */

export interface ResearchLead {
  opportunity_id: string;
  faculty: FacultyRef;
  lab: LabRef | null;
  lead_state: LeadState;
  fit_score: number | null;
  fit_confidence: number | null;
  topics: TopicRef[];
  overlap: TopicOverlap[];
  latest_evidence: ResearchEvidenceItem | null;
  evidence_count: number;
  signals: LabSignalItem[];
  status: OpportunityStatus;
  deadline: string | null;
  deadline_state: DeadlineState;
  urgency: Urgency;
}

/** Facet rows always carry a label; it falls back to the raw value server-side. */
export interface FacetValue {
  value: string;
  label?: string | null;
  count: number;
}

export interface ResearchFacets {
  departments: FacetValue[];
  topics: FacetValue[];
  states: FacetValue[];
}

/* -------------------------------------------------------------- applications */

export type ReadinessState = "ready" | "attention" | "blocked" | "unknown";
export type LinkVerification = "verified" | "unverified" | "not_found";

export interface ReadinessItem {
  key: string;
  label: string;
  state: ReadinessState;
  detail: string;
  note: string | null;
}

/**
 * The one answer to "Can I apply right now?", computed server-side so the
 * opportunity panel and the kit page cannot disagree. `cta` is only ever
 * "Continue preparation" or "Review application" — Trellis never submits, so
 * it never offers "Apply".
 */
export interface ApplicationReadiness {
  ready: boolean;
  cta: string;
  cta_action: "prepare" | "review";
  items: ReadinessItem[];
  blocking: string[];
  application_link: LinkVerification;
  application_link_note: string | null;
  application_url: string | null;
  has_application: boolean;
  application_id: string | null;
}

export interface ApplicationDocumentItem {
  id: string;
  kind: string;
  label: string;
  status: "ready" | "missing" | "needs_user";
  required: boolean;
  resume_id: string | null;
  filename: string | null;
  note: string | null;
  source_text: string | null;
}

export type AnswerCategory =
  | "safe_profile_field"
  | "safe_generative"
  | "sensitive"
  | "unknown";

export interface ApplicationAnswerItem {
  id: string;
  question: string;
  field_key: string | null;
  answer: string | null;
  source: "profile" | "user" | "llm_draft";
  profile_field: string | null;
  /** What Trellis is allowed to do with this question. */
  category: AnswerCategory;
  is_sensitive: boolean;
  sensitive_category: string | null;
  reuse_approved: boolean;
  needs_user_input: boolean;
  max_length: number | null;
}

export interface ApplicationEventItem {
  id: string;
  kind: string;
  from_status: string | null;
  to_status: string | null;
  actor: string;
  note: string | null;
  created_at: string;
}

export interface ApplicationKit {
  id: string;
  status: OpportunityStatus;
  opportunity: OpportunityListItem;
  application_url: string | null;
  application_method: string | null;
  resume_id: string | null;
  resume_label: string | null;
  resume_locked_by_user: boolean;
  resume_recommendations: ResumeRecommendationItem[];
  documents: ApplicationDocumentItem[];
  answers: ApplicationAnswerItem[];
  known_profile_fields: { key: string; label: string; value: string | null }[];
  readiness: ApplicationReadiness;
  blocking: string[];
  ready: boolean;
  prepared_at: string | null;
  approved_at: string | null;
  submitted_at: string | null;
  notes: string | null;
  events: ApplicationEventItem[];
}

export interface SubmissionPlanField {
  key: string;
  label: string;
  value: string | null;
  source: "profile" | "user" | "resume" | "llm_draft";
  is_sensitive: boolean;
  will_submit: boolean;
  note: string | null;
}

export interface SubmissionPlan {
  application_id: string;
  target_url: string | null;
  method: string | null;
  fields: SubmissionPlanField[];
  attachments: { kind: string; filename: string; label: string }[];
  withheld: { label: string; reason: string }[];
  manual_steps: string[];
  requires_user_at: string[];
  payload_hash: string;
  approved: boolean;
}

/* ------------------------------------------------------------------ resumes */

export interface ResumeItem {
  id: string;
  label: string;
  original_filename: string;
  size_bytes: number;
  page_count: number | null;
  is_default: boolean;
  parse_status: "pending" | "parsed" | "failed";
  parse_error: string | null;
  detected_skills: string[];
  detected_topics: string[];
  highlight_count: number;
  created_at: string;
}

export interface ResumeDetail extends ResumeItem {
  text_preview: string | null;
  highlights: { id: string; section: string | null; text: string; skills: string[]; topics: string[] }[];
  stats: Record<string, unknown>;
}

/* ------------------------------------------------------------------ profile */

export interface ProfileSkillItem {
  id: string;
  slug: string;
  label: string;
  category: string | null;
  origin: "user" | "resume";
  proficiency: string | null;
  evidence: string | null;
}

export interface ProfileInterestItem {
  id: string;
  label: string;
  topic_slug: string | null;
  weight: number;
  note: string | null;
}

export interface CourseworkItem {
  id: string;
  code: string | null;
  title: string;
  term: string | null;
  grade: string | null;
  topics: string[];
}

export interface ExperienceItem {
  id: string;
  organization: string;
  role: string;
  kind: string | null;
  started_on: string | null;
  ended_on: string | null;
  summary: string | null;
  highlights: string[];
  skills: string[];
  origin: string;
}

export interface StudentProfile {
  id: string;
  user_id: string;
  email: string;
  display_name: string | null;
  university: string;
  campus: string | null;
  major: string | null;
  secondary_major: string | null;
  degree: string | null;
  graduation_year: number | null;
  gpa: number | null;
  /** GPA is only reused in applications when the student switches this on. */
  gpa_is_public: boolean;
  work_authorization: string;
  work_authorization_note: string | null;
  hours_per_week_min: number | null;
  hours_per_week_max: number | null;
  preferred_job_types: string[];
  preferred_locations: string[];
  keywords: string[];
  availability_note: string | null;
  /** Durable UI choices that belong to the student, not the browser. */
  preferences: { opportunityFocus?: "interests" | "all" } & Record<string, unknown>;
  onboarding_completed_at: string | null;
  skills: ProfileSkillItem[];
  interests: ProfileInterestItem[];
  coursework: CourseworkItem[];
  experiences: ExperienceItem[];
  resume_count: number;
}

/* ----------------------------------------------------------------- overview */

export interface ActionItem {
  opportunity: OpportunityListItem;
  reason: string;
  blocking: string[];
  resume_ready: boolean;
  application_id: string | null;
  cta: string;
}

export interface PipelineStage {
  status: OpportunityStatus;
  label: string;
  count: number;
}

export interface Overview {
  profile_name: string | null;
  university: string;
  action_needed: ActionItem[];
  due_soon: OpportunityListItem[];
  best_matches: OpportunityListItem[];
  /** The rows you marked interested, newest first. Your choice, not a ranking. */
  interested: OpportunityListItem[];
  research_leads: ResearchLead[];
  recent_discoveries: OpportunityListItem[];
  pipeline: PipelineStage[];
  counts: {
    total: number;
    saved: number;
    /** Faculty-linked leads — the same set /research shows. */
    lab_leads: number;
    verified_openings: number;
    outreach: number;
    /** Formal programmes (CURIS, VPUE grants) with no PI attached. */
    research_programs: number;
    unread: number;
  };
  last_run: SearchRunSummary | null;
  needs_onboarding: boolean;
}

/* --------------------------------------------------------------- searching */

export interface SearchRunSummary {
  id: string;
  kind: "jobs" | "research";
  status: "queued" | "running" | "succeeded" | "partial" | "failed" | "cancelled";
  trigger: string;
  started_at: string | null;
  finished_at: string | null;
  /**
   * The run ledger. Every document a run looked at lands in exactly one of
   * these, so "we found nothing" and "we withheld things" never look alike.
   */
  created_count: number;
  updated_count: number;
  unchanged_count: number;
  expired_count: number;
  held_count: number;
  skipped_count: number;
  suppressed_count: number;
  documents_fetched: number;
  sources_attempted: string[];
  error: string | null;
  steps: { step: string; detail: string; status: string }[];
}

export interface SavedSearchItem {
  id: string;
  name: string;
  kind: "jobs" | "research";
  query: string | null;
  source_slugs: string[];
  enabled: boolean;
  last_run_at: string | null;
  filters: Record<string, unknown>;
}

/* --------------------------------------------------------------- reminders */

export interface ReminderItem {
  id: string;
  title: string;
  due_on: string | null;
  offsets_days: number[];
  provider: "ics" | "apple_shortcuts" | "none";
  status: "pending" | "exported" | "dismissed";
  opportunity_id: string | null;
  url: string | null;
  documents: string[];
  notes: string | null;
}

export interface ReminderProviderInfo {
  slug: string;
  label: string;
  description: string;
  requires_user_action: boolean;
}

/* ------------------------------------------------------------------ common */

export interface Paginated<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface OpportunityFacets {
  types: { value: OpportunityType; count: number }[];
  statuses: { value: OpportunityStatus; count: number }[];
  sources: { value: string; label: string; count: number }[];
  topics: { value: string; label: string; count: number }[];
  departments: { value: string; count: number }[];
  /**
   * The only facet counted across both sides of the gate, because it is the
   * control that crosses it. Every other count describes the recommended set.
   */
  confidence: { value: ConfidenceState; label: string; count: number }[];
}

export interface OpportunityListResponse extends Paginated<OpportunityListItem> {
  facets: OpportunityFacets;
  /**
   * How many rows these same filters matched but were dropped for being
   * hidden. Sent so the omission can be stated with a number and undone.
   */
  hidden_count: number;
}

export interface DataSourceInfo extends SourceRef {
  enabled: boolean;
  last_run_at: string | null;
  opportunity_count: number;
  notes: string | null;
}

export interface ProvenanceInfo {
  key: string;
  label: string;
  generated_at: string | null;
  detail: Record<string, unknown>;
}

/* ------------------------------------------------------------------ changes */

export type ChangeKind =
  | "discovered"
  | "deadline"
  | "requirement_added"
  | "requirement_removed"
  | "pay"
  | "hours"
  | "application_url"
  | "recruiting_status"
  | "lead_state"
  | "expired"
  | "disappeared"
  | "reappeared";

export interface OpportunityChangeItem {
  id: string;
  opportunity_id: string;
  opportunity_title: string;
  kind: ChangeKind;
  field: string | null;
  old_value: string | null;
  new_value: string | null;
  summary: string;
  source_url: string | null;
  noticed_at: string;
  seen: boolean;
}

export interface OutreachCitation {
  label: string;
  detail: string;
  source_url: string | null;
  side: "research" | "student";
}

export interface OutreachDraft {
  subject: string | null;
  body: string | null;
  word_count: number;
  research_citations: OutreachCitation[];
  student_citations: OutreachCitation[];
  /** Set when Trellis will not draft. Shown instead of an email, never beside one. */
  refusal: string | null;
  todos: string[];
}
