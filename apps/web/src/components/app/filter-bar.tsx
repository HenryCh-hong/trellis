"use client";

/**
 * Filter bar for the opportunities table.
 *
 * Every control here filters the already-loaded result set in the browser, so
 * typing is instant and nothing round-trips. The caller mirrors the resulting
 * state into the query string with `history.replaceState`, which keeps a view
 * linkable and refresh-proof without re-rendering the server component.
 */

import * as React from "react";
import { statusLabel } from "@/components/app/indicators";
import { Button, Spinner } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { Alert, SegmentedControl } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  EligibilityState,
  OpportunityDetail,
  OpportunityFacets,
  OpportunityStatus,
  OpportunityType,
} from "@/lib/types";

/* ----------------------------------------------------------------- state */

export type SortKey = "recommended" | "deadline" | "fit" | "discovered";

export interface OpportunityFilters {
  /** "interests" narrows to what you said you care about. */
  focus: "interests" | "all";
  q: string;
  type: OpportunityType | "";
  status: OpportunityStatus | "";
  source: string;
  topic: string;
  department: string;
  campus: string;
  eligibility: EligibilityState | "";
  minFit: number;
  sort: SortKey;
}

export interface FacetOption {
  value: string;
  label: string;
  count: number;
}

const TYPES = [
  "on_campus",
  "part_time",
  "research_opening",
  "research_outreach",
] as const satisfies readonly OpportunityType[];

const STATUSES = [
  "new",
  "saved",
  "preparing",
  "ready_to_apply",
  "applying",
  "submitted",
  "interview",
  "offer",
  "rejected",
  "archived",
] as const satisfies readonly OpportunityStatus[];

const ELIGIBILITIES = [
  "eligible",
  "likely_eligible",
  "unclear",
  "ineligible",
] as const satisfies readonly EligibilityState[];

const SORTS = ["recommended", "deadline", "fit", "discovered"] as const satisfies readonly SortKey[];

const TYPE_LABEL: Record<OpportunityType, string> = {
  on_campus: "On-campus",
  part_time: "Part-time",
  research_opening: "Research opening",
  research_outreach: "Outreach",
};

export const ELIGIBILITY_LABEL: Record<EligibilityState, string> = {
  eligible: "Eligible",
  likely_eligible: "Likely eligible",
  unclear: "Unclear",
  ineligible: "Not eligible",
};

const SORT_LABEL: Record<SortKey, string> = {
  recommended: "Recommended",
  deadline: "Deadline",
  fit: "Fit",
  discovered: "Recently discovered",
};

export const DEFAULT_FILTERS: OpportunityFilters = {
  // Interests-first by default: the point of stating them is that they narrow
  // what you have to read. One click widens it again.
  focus: "interests",
  q: "",
  type: "",
  status: "",
  source: "",
  topic: "",
  department: "",
  campus: "",
  eligibility: "",
  minFit: 0,
  sort: "recommended",
};

/** Short query-string keys — the URL is meant to be pasted into a message. */
const PARAM: Record<keyof OpportunityFilters, string> = {
  focus: "focus",
  q: "q",
  type: "type",
  status: "status",
  source: "src",
  topic: "topic",
  department: "dept",
  campus: "campus",
  eligibility: "elig",
  minFit: "min",
  sort: "sort",
};

interface ReadonlySearchParams {
  get(name: string): string | null;
}

function member<T extends string>(value: string, list: readonly T[]): T | "" {
  return (list as readonly string[]).includes(value) ? (value as T) : "";
}

export function parseFilters(sp: ReadonlySearchParams): OpportunityFilters {
  const read = (key: string) => sp.get(key) ?? "";
  const min = Number.parseInt(read(PARAM.minFit), 10);
  return {
    focus: read(PARAM.focus) === "all" ? "all" : DEFAULT_FILTERS.focus,
    q: read(PARAM.q),
    type: member(read(PARAM.type), TYPES),
    status: member(read(PARAM.status), STATUSES),
    source: read(PARAM.source),
    topic: read(PARAM.topic),
    department: read(PARAM.department),
    campus: read(PARAM.campus),
    eligibility: member(read(PARAM.eligibility), ELIGIBILITIES),
    minFit: Number.isFinite(min) && min > 0 && min <= 100 ? min : 0,
    sort: member(read(PARAM.sort), SORTS) || DEFAULT_FILTERS.sort,
  };
}

export function filtersToQuery(f: OpportunityFilters): string {
  const sp = new URLSearchParams();
  if (f.focus !== DEFAULT_FILTERS.focus) sp.set(PARAM.focus, f.focus);
  if (f.q) sp.set(PARAM.q, f.q);
  if (f.type) sp.set(PARAM.type, f.type);
  if (f.status) sp.set(PARAM.status, f.status);
  if (f.source) sp.set(PARAM.source, f.source);
  if (f.topic) sp.set(PARAM.topic, f.topic);
  if (f.department) sp.set(PARAM.department, f.department);
  if (f.campus) sp.set(PARAM.campus, f.campus);
  if (f.eligibility) sp.set(PARAM.eligibility, f.eligibility);
  if (f.minFit > 0) sp.set(PARAM.minFit, String(f.minFit));
  if (f.sort !== DEFAULT_FILTERS.sort) sp.set(PARAM.sort, f.sort);
  const s = sp.toString();
  return s ? `?${s}` : "";
}

type ChipKey = Exclude<keyof OpportunityFilters, "sort">;

/* ------------------------------------------------------------------- bar */

export function FilterBar({
  filters,
  onChange,
  facets,
  campusOptions,
  eligibilityOptions,
  onImport,
  relevantCount = null,
  totalCount = null,
  className,
}: {
  filters: OpportunityFilters;
  onChange: (next: OpportunityFilters) => void;
  facets: OpportunityFacets;
  campusOptions: FacetOption[];
  relevantCount?: number | null;
  totalCount?: number | null;
  eligibilityOptions: FacetOption[];
  onImport: () => void;
  className?: string;
}) {
  const set = React.useCallback(
    <K extends keyof OpportunityFilters>(key: K, value: OpportunityFilters[K]) =>
      onChange({ ...filters, [key]: value }),
    [filters, onChange],
  );

  const [advanced, setAdvanced] = React.useState(false);

  // Six selects on screen at all times is more chrome than most sessions need.
  // They collapse, but the count stays visible so a filter can never be on
  // without the student being able to see that it is.
  const activeSecondary = [
    filters.type,
    filters.status,
    filters.source,
    filters.topic,
    filters.department,
    filters.campus,
    filters.eligibility,
    filters.minFit > 0 ? "y" : "",
  ].filter(Boolean).length;

  const chips: { key: ChipKey; label: string }[] = [];
  if (filters.q) chips.push({ key: "q", label: `“${filters.q}”` });
  if (filters.type) chips.push({ key: "type", label: TYPE_LABEL[filters.type] });
  if (filters.status) chips.push({ key: "status", label: statusLabel(filters.status) });
  if (filters.source) {
    const f = facets.sources.find((s) => s.value === filters.source);
    chips.push({ key: "source", label: f?.label ?? filters.source });
  }
  if (filters.topic) {
    const f = facets.topics.find((t) => t.value === filters.topic);
    chips.push({ key: "topic", label: f?.label ?? filters.topic });
  }
  if (filters.department) chips.push({ key: "department", label: filters.department });
  if (filters.campus) chips.push({ key: "campus", label: filters.campus });
  if (filters.eligibility) {
    chips.push({ key: "eligibility", label: ELIGIBILITY_LABEL[filters.eligibility] });
  }
  if (filters.minFit > 0) chips.push({ key: "minFit", label: `Fit ${filters.minFit}+` });

  return (
    <div className={cn("border-t border-[var(--border-subtle)]", className)}>
      <div className="flex flex-wrap items-center gap-1.5 px-5 py-2" role="search">
        {/* The first control, because narrowing to what you care about does more
            than any other filter here. Counts make the trade-off visible. */}
        <SegmentedControl
          className="mr-1"
          options={[
            {
              value: "interests",
              label: relevantCount === null ? "My interests" : `My interests · ${relevantCount}`,
            },
            { value: "all", label: totalCount === null ? "Everything" : `Everything · ${totalCount}` },
          ]}
          value={filters.focus}
          onChange={(v) => set("focus", v as OpportunityFilters["focus"])}
        />

        <Input
          type="search"
          value={filters.q}
          onChange={(e) => set("q", e.target.value)}
          placeholder="Search titles, labs, people…"
          aria-label="Search opportunities"
          className="h-7 w-[210px] text-xs"
        />

        {advanced && (
          <div className="flex w-full flex-wrap items-center gap-1.5 pt-1.5">
          <FilterSelect
            width="w-[122px]"
            label="All types"
            value={filters.type}
            onChange={(v) => set("type", member(v, TYPES))}
            options={facets.types.map((t) => ({
              value: t.value,
              label: TYPE_LABEL[t.value],
              count: t.count,
            }))}
          />
          <FilterSelect
            width="w-[116px]"
            label="Any status"
            value={filters.status}
            onChange={(v) => set("status", member(v, STATUSES))}
            options={facets.statuses.map((s) => ({
              value: s.value,
              label: statusLabel(s.value),
              count: s.count,
            }))}
          />
          <FilterSelect
            width="w-[130px]"
            label="All sources"
            value={filters.source}
            onChange={(v) => set("source", v)}
            options={facets.sources.map((s) => ({ value: s.value, label: s.label, count: s.count }))}
          />
          <FilterSelect
            width="w-[128px]"
            label="All topics"
            value={filters.topic}
            onChange={(v) => set("topic", v)}
            options={facets.topics.map((t) => ({ value: t.value, label: t.label, count: t.count }))}
          />
          <FilterSelect
            width="w-[136px]"
            label="All departments"
            value={filters.department}
            onChange={(v) => set("department", v)}
            options={facets.departments.map((d) => ({
              value: d.value,
              label: d.value,
              count: d.count,
            }))}
          />
          <FilterSelect
            width="w-[124px]"
            label="Any campus"
            value={filters.campus}
            onChange={(v) => set("campus", v)}
            options={campusOptions}
          />
          <FilterSelect
            width="w-[132px]"
            label="Any eligibility"
            value={filters.eligibility}
            onChange={(v) => set("eligibility", member(v, ELIGIBILITIES))}
            options={eligibilityOptions}
          />

          <div className="w-[108px] shrink-0">
            <Select
              aria-label="Minimum fit score"
              className="h-7 w-full pl-2 pr-6 text-xs"
              value={String(filters.minFit)}
              onChange={(e) => set("minFit", Number.parseInt(e.target.value, 10) || 0)}
            >
              <option value="0">Any fit</option>
              {[40, 50, 60, 70, 80, 90].map((n) => (
                <option key={n} value={n}>
                  Min fit {n}
                </option>
              ))}
            </Select>
          </div>
          </div>
        )}

        <button
          type="button"
          onClick={() => setAdvanced((v) => !v)}
          aria-expanded={advanced}
          className={cn(
            "h-7 shrink-0 rounded-[var(--radius-sm)] border px-2 text-xs transition-colors",
            advanced || activeSecondary > 0
              ? "border-[var(--accent-border)] bg-[var(--accent-soft)] text-[var(--color-accent-700)]"
              : "border-[var(--border)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]",
          )}
        >
          Filters{activeSecondary > 0 ? ` · ${activeSecondary}` : ""}
        </button>

        <div className="ml-auto flex items-center gap-1.5">
          <span className="hidden text-2xs uppercase tracking-[0.05em] text-[var(--text-tertiary)] sm:inline">
            Sort
          </span>
          <div className="w-[168px] shrink-0">
            <Select
              aria-label="Sort opportunities"
              className="h-7 w-full pl-2 pr-6 text-xs"
              value={filters.sort}
              onChange={(e) => set("sort", member(e.target.value, SORTS) || "recommended")}
            >
              {SORTS.map((s) => (
                <option key={s} value={s}>
                  {SORT_LABEL[s]}
                </option>
              ))}
            </Select>
          </div>
          <Button size="sm" variant="secondary" onClick={onImport}>
            Import URL
          </Button>
        </div>
      </div>

      {chips.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 border-t border-[var(--border-subtle)] px-5 py-1.5">
          <span className="text-2xs uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
            Filters
          </span>
          {chips.map((chip) => (
            <button
              key={chip.key}
              onClick={() => onChange({ ...filters, [chip.key]: DEFAULT_FILTERS[chip.key] })}
              className={cn(
                "inline-flex h-[20px] max-w-[220px] items-center gap-1 rounded-[var(--radius-xs)] pl-1.5 pr-1",
                "border border-[var(--accent-border)] bg-[var(--accent-soft)]",
                "text-2xs font-medium text-[var(--color-accent-700)]",
                "transition-colors duration-100 hover:bg-[var(--color-accent-100)]",
              )}
            >
              <span className="truncate">{chip.label}</span>
              <svg className="size-2.5 shrink-0 opacity-70" viewBox="0 0 10 10" fill="none" aria-hidden>
                <path d="M2.5 2.5l5 5M7.5 2.5l-5 5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
              </svg>
              <span className="sr-only">Remove filter</span>
            </button>
          ))}
          <button
            onClick={() => onChange({ ...DEFAULT_FILTERS, sort: filters.sort })}
            className="ml-1 text-2xs font-medium text-[var(--text-tertiary)] underline-offset-2 hover:text-[var(--text-primary)] hover:underline"
          >
            Clear all
          </button>
        </div>
      )}
    </div>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
  width,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: FacetOption[];
  width: string;
}) {
  // A facet with nothing behind it is a dead control — hide it rather than
  // offering a filter that can only ever return zero rows.
  if (options.length === 0) return null;
  return (
    <div className={cn("shrink-0", width)}>
      <Select
        aria-label={label}
        className="h-7 w-full pl-2 pr-6 text-xs"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">{label}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label} · {o.count}
          </option>
        ))}
      </Select>
    </div>
  );
}

/* ---------------------------------------------------------- import dialog */

/** Mounted only while it is open, so every visit starts from a blank field. */
export function ImportUrlDialog({
  onClose,
  onImported,
}: {
  onClose: () => void;
  onImported: (detail: OpportunityDetail) => void;
}) {
  const [url, setUrl] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const submit = async () => {
    const trimmed = url.trim();
    if (!trimmed) {
      setError("Paste a link first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const detail = await api.opportunities.importUrl(trimmed);
      onImported(detail);
      onClose();
    } catch (err) {
      // The failure stays in the dialog: an import error is something to read
      // and act on, not a toast that vanishes before it can be understood.
      setError(
        err instanceof ApiError
          ? err.message
          : "The import failed for an unknown reason. Check the link and try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center px-4 pt-[16vh]"
      onKeyDown={(e) => {
        // Stop here so the list's global shortcuts and the side panel's own
        // Escape handler don't also fire while the dialog owns the keyboard.
        e.stopPropagation();
        if (e.key === "Escape" && !busy) onClose();
        if (e.key === "Enter" && !busy) void submit();
      }}
    >
      <div
        className="absolute inset-0 bg-[var(--color-neutral-950)]/[0.12] animate-fade-in"
        onClick={() => !busy && onClose()}
        aria-hidden
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="import-url-title"
        className={cn(
          "relative w-full max-w-[460px] animate-rise rounded-[var(--radius-lg)]",
          "border border-[var(--border)] bg-[var(--bg)] shadow-pop",
        )}
      >
        <div className="px-4 pb-3 pt-3.5">
          <h2 id="import-url-title" className="text-sm font-semibold text-[var(--text-primary)]">
            Import from a URL
          </h2>
          <p className="mt-1 text-xs leading-relaxed text-[var(--text-tertiary)]">
            Paste a job posting, program page, or a professor&rsquo;s page. Trellis reads the page
            and records only what it can actually find there.
          </p>
        </div>

        <div className="flex flex-col gap-2 px-4 pb-3">
          <Input
            ref={inputRef}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://cs.stanford.edu/…"
            aria-label="URL to import"
            disabled={busy}
            spellCheck={false}
            autoComplete="off"
          />
          {error && (
            <Alert tone="danger" title="Import failed">
              {error}
            </Alert>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-[var(--border-subtle)] bg-[var(--bg-subtle)] px-4 py-2.5">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" size="sm" onClick={() => void submit()} disabled={busy}>
            {busy && <Spinner />}
            {busy ? "Reading the page…" : "Import"}
          </Button>
        </div>
      </div>
    </div>
  );
}
