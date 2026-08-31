/**
 * Typed API client.
 *
 * One place that knows the base URL and error shape. Server components call
 * these directly; client components call them through hooks in `src/hooks`.
 */

import type {
  ApplicationKit,
  DataSourceInfo,
  FeedbackReason,
  FeedbackSignal,
  OpportunityChangeItem,
  OpportunityDetail,
  OpportunityFeedback,
  OpportunityListResponse,
  OutreachDraft,
  Overview,
  ProvenanceInfo,
  ReminderItem,
  ReminderProviderInfo,
  ResearchContext,
  ResearchFacets,
  ResearchLead,
  ResumeDetail,
  ResumeItem,
  SavedSearchItem,
  SearchRunSummary,
  StudentProfile,
  SubmissionPlan,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Query = Record<string, string | number | boolean | string[] | null | undefined>;

function buildQuery(params?: Query): string {
  if (!params) return "";
  const sp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    if (Array.isArray(value)) {
      for (const v of value) if (v !== "") sp.append(key, String(v));
    } else {
      sp.set(key, String(value));
    }
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit & { query?: Query },
): Promise<T> {
  const { query, ...rest } = init ?? {};
  const url = `${API_BASE}${path}${buildQuery(query)}`;
  let res: Response;
  try {
    res = await fetch(url, {
      cache: "no-store",
      ...rest,
      headers: {
        ...(rest.body && !(rest.body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
        ...rest.headers,
      },
    });
  } catch (cause) {
    throw new ApiError(
      "Could not reach the Trellis API. Is the backend running on port 8000?",
      0,
      cause,
    );
  }

  if (res.status === 204) return undefined as T;

  const text = await res.text();
  let body: unknown = text;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    /* keep raw text */
  }

  if (!res.ok) {
    const detail =
      typeof body === "object" && body !== null && "detail" in body
        ? (body as { detail: unknown }).detail
        : body;
    throw new ApiError(
      typeof detail === "string" ? detail : `Request failed (${res.status})`,
      res.status,
      detail,
    );
  }
  return body as T;
}

export const api = {
  overview: () => apiFetch<Overview>("/api/overview"),

  profile: {
    get: () => apiFetch<StudentProfile | null>("/api/profile"),
    update: (patch: Partial<StudentProfile>) =>
      apiFetch<StudentProfile>("/api/profile", {
        method: "PATCH",
        body: JSON.stringify(patch),
      }),
    onboard: (payload: unknown) =>
      apiFetch<{ profile: StudentProfile; run_ids: string[] }>("/api/onboarding", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    addSkill: (label: string) =>
      apiFetch<StudentProfile>("/api/profile/skills", {
        method: "POST",
        body: JSON.stringify({ label }),
      }),
    removeSkill: (id: string) =>
      apiFetch<StudentProfile>(`/api/profile/skills/${id}`, { method: "DELETE" }),
    addInterest: (label: string, weight = 1) =>
      apiFetch<StudentProfile>("/api/profile/interests", {
        method: "POST",
        body: JSON.stringify({ label, weight }),
      }),
    removeInterest: (id: string) =>
      apiFetch<StudentProfile>(`/api/profile/interests/${id}`, { method: "DELETE" }),
    addCourse: (payload: { code?: string; title: string; term?: string }) =>
      apiFetch<StudentProfile>("/api/profile/coursework", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    removeCourse: (id: string) =>
      apiFetch<StudentProfile>(`/api/profile/coursework/${id}`, { method: "DELETE" }),
  },

  opportunities: {
    list: (query?: Query) =>
      apiFetch<OpportunityListResponse>("/api/opportunities", { query }),
    get: (id: string) => apiFetch<OpportunityDetail>(`/api/opportunities/${id}`),
    setStatus: (id: string, status: string) =>
      apiFetch<OpportunityDetail>(`/api/opportunities/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      }),
    update: (id: string, patch: Record<string, unknown>) =>
      apiFetch<OpportunityDetail>(`/api/opportunities/${id}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      }),
    importUrl: (url: string) =>
      apiFetch<OpportunityDetail>("/api/opportunities/import", {
        method: "POST",
        body: JSON.stringify({ url }),
      }),
    changes: (limit = 25) =>
      apiFetch<OpportunityChangeItem[]>("/api/changes", { query: { limit } }),
    rematch: (id: string) =>
      apiFetch<OpportunityDetail>(`/api/opportunities/${id}/rematch`, {
        method: "POST",
      }),
    /** Record what you said about one opportunity. Re-posting replaces it. */
    feedback: (
      id: string,
      payload: { signal: FeedbackSignal; reason?: FeedbackReason; note?: string },
    ) =>
      apiFetch<OpportunityFeedback>(`/api/opportunities/${id}/feedback`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    /** Undo. The row is deleted, so nothing of it survives in the ranking. */
    clearFeedback: (id: string) =>
      apiFetch<void>(`/api/opportunities/${id}/feedback`, { method: "DELETE" }),
  },

  research: {
    leads: (query?: Query) =>
      apiFetch<{ items: ResearchLead[]; total: number; facets: ResearchFacets }>(
        "/api/research/leads",
        { query },
      ),
    faculty: (id: string) => apiFetch<ResearchContext>(`/api/research/faculty/${id}`),
    outreach: (id: string) =>
      apiFetch<OutreachDraft>(`/api/research/faculty/${id}/outreach`),
    topics: () =>
      apiFetch<{ slug: string; label: string; parent_slug: string | null; count: number }[]>(
        "/api/research/topics",
      ),
  },

  applications: {
    list: () => apiFetch<ApplicationKit[]>("/api/applications"),
    create: (opportunityId: string) =>
      apiFetch<ApplicationKit>("/api/applications", {
        method: "POST",
        body: JSON.stringify({ opportunity_id: opportunityId }),
      }),
    get: (id: string) => apiFetch<ApplicationKit>(`/api/applications/${id}`),
    update: (id: string, patch: Record<string, unknown>) =>
      apiFetch<ApplicationKit>(`/api/applications/${id}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      }),
    answer: (id: string, answerId: string, patch: Record<string, unknown>) =>
      apiFetch<ApplicationKit>(`/api/applications/${id}/answers/${answerId}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      }),
    plan: (id: string) => apiFetch<SubmissionPlan>(`/api/applications/${id}/plan`),
    approve: (id: string, payloadHash: string) =>
      apiFetch<ApplicationKit>(`/api/applications/${id}/approve`, {
        method: "POST",
        body: JSON.stringify({ payload_hash: payloadHash }),
      }),
    markSubmitted: (id: string) =>
      apiFetch<ApplicationKit>(`/api/applications/${id}/submitted`, { method: "POST" }),
  },

  resumes: {
    list: () => apiFetch<ResumeItem[]>("/api/resumes"),
    get: (id: string) => apiFetch<ResumeDetail>(`/api/resumes/${id}`),
    upload: (file: File, label: string) => {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("label", label);
      return apiFetch<ResumeItem>("/api/resumes", { method: "POST", body: fd });
    },
    remove: (id: string) => apiFetch<void>(`/api/resumes/${id}`, { method: "DELETE" }),
    setDefault: (id: string) =>
      apiFetch<ResumeItem>(`/api/resumes/${id}/default`, { method: "POST" }),
    fileUrl: (id: string) => `${API_BASE}/api/resumes/${id}/file`,
  },

  searches: {
    list: () => apiFetch<SavedSearchItem[]>("/api/searches"),
    create: (payload: Record<string, unknown>) =>
      apiFetch<SavedSearchItem>("/api/searches", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    run: (id: string) =>
      apiFetch<SearchRunSummary>(`/api/searches/${id}/run`, { method: "POST" }),
    runs: () => apiFetch<SearchRunSummary[]>("/api/runs"),
    run_detail: (id: string) => apiFetch<SearchRunSummary>(`/api/runs/${id}`),
    discover: (kind: "jobs" | "research") =>
      apiFetch<SearchRunSummary>("/api/searches/discover", {
        method: "POST",
        body: JSON.stringify({ kind }),
      }),
  },

  reminders: {
    list: () => apiFetch<ReminderItem[]>("/api/reminders"),
    create: (payload: Record<string, unknown>) =>
      apiFetch<ReminderItem>("/api/reminders", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    remove: (id: string) => apiFetch<void>(`/api/reminders/${id}`, { method: "DELETE" }),
    providers: () => apiFetch<ReminderProviderInfo[]>("/api/reminders/providers"),
    icsUrl: (id: string) => `${API_BASE}/api/reminders/${id}/export.ics`,
    appleAvailability: () =>
      apiFetch<{ available: boolean; reason: string; needs_permission: boolean }>(
        "/api/reminders/apple/availability",
      ),
    sendToApple: (id: string) =>
      apiFetch<{ created: { title: string; alert_on: string }[]; note: string }>(
        `/api/reminders/${id}/apple`,
        { method: "POST" },
      ),
    shortcut: (id: string) =>
      apiFetch<Record<string, unknown>>(`/api/reminders/${id}/shortcut`),
  },

  settings: {
    sources: () => apiFetch<DataSourceInfo[]>("/api/sources"),
    provenance: () => apiFetch<ProvenanceInfo[]>("/api/provenance"),
    deleteAccount: () => apiFetch<void>("/api/account", { method: "DELETE" }),
  },
};
