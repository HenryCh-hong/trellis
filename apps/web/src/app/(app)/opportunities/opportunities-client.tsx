"use client";

/**
 * Opportunities — the workhorse list.
 *
 * The whole result set is loaded once and every filter, search and sort runs
 * in the browser. That is what makes typing feel instant, and it keeps the
 * URL as the single shareable description of a view: filter state is mirrored
 * with `history.replaceState`, which `useSearchParams` picks up without
 * re-rendering the server component.
 */

import * as React from "react";
import { usePathname, useSearchParams } from "next/navigation";
import {
  DeadlineCell,
  ScoreMeter,
  SourceStatusBadge,
  StatusPill,
  TypeTag,
} from "@/components/app/indicators";
import {
  DEFAULT_FILTERS,
  ELIGIBILITY_LABEL,
  FilterBar,
  ImportUrlDialog,
  filtersToQuery,
  parseFilters,
  type FacetOption,
  type OpportunityFilters,
} from "@/components/app/filter-bar";
import { OpportunityPanel } from "@/components/app/opportunity/detail-panel";
import { RowFeedbackControls } from "@/components/app/opportunity/feedback-controls";
import { PageHeader } from "@/components/app/page-header";
import { Button } from "@/components/ui/button";
import { EmptyState, Tooltip } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { isHidden, sortAdjustment } from "@/lib/feedback";
import { cn, hostOf } from "@/lib/utils";
import type {
  EligibilityState,
  OpportunityDetail,
  OpportunityFacets,
  OpportunityListItem,
  Urgency,
} from "@/lib/types";

/* ------------------------------------------------------- derived facets */

/**
 * Locations arrive as free text ("Stanford, CA (Gates Building, 353 Jane
 * Stanford Way)"), so the campus facet is the part before the street detail.
 * Nothing is invented — it is a prefix of what the source actually said.
 */
function campusOf(location: string | null): string | null {
  if (!location) return null;
  const head = location.split("(")[0].trim().replace(/[,;·]+$/, "").trim();
  return head || null;
}

function countBy<T>(items: OpportunityListItem[], key: (i: OpportunityListItem) => T | null) {
  const counts = new Map<T, number>();
  for (const item of items) {
    const value = key(item);
    if (value === null) continue;
    counts.set(value, (counts.get(value) ?? 0) + 1);
  }
  return counts;
}

const ELIGIBILITY_ORDER: EligibilityState[] = [
  "eligible",
  "likely_eligible",
  "unclear",
  "ineligible",
];

/* -------------------------------------------------------------- filtering */

function haystackOf(item: OpportunityListItem): string {
  return [
    item.title,
    item.organization,
    item.department,
    item.lab_name,
    item.pi_name,
    item.location,
    item.source?.name,
    hostOf(item.source_url),
    ...item.topics.map((t) => t.label),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

/**
 * Expired rows are hidden by default — but only the untouched ones.
 *
 * A deadline that has passed is noise in a list of things to do, so it leaves
 * the default view. The test is `status === "new"`: the moment you save one,
 * archive it or start an application, you have touched it, and it stays
 * exactly where you left it. Hiding something you acted on would be the app
 * quietly losing your work, and the record is the whole point of keeping it.
 */
function hiddenAsExpired(item: OpportunityListItem): boolean {
  return (
    item.deadline_state === "expired" && item.status === "new" && !item.has_application
  );
}

function matchesFilters(
  item: OpportunityListItem,
  f: OpportunityFilters,
  haystack: string,
): boolean {
  // First and unconditional: a held row was one Trellis could barely read, and
  // it may never appear beside a real posting with nothing to distinguish it.
  if (item.confidence_state !== f.confidence) return false;
  // Second: something you put away stays away, whatever else is on. Counted at
  // the foot of the list and one click from coming back.
  if (!f.showHidden && isHidden(item)) return false;
  if (!f.showExpired && hiddenAsExpired(item)) return false;
  if (f.focus === "interests" && !item.matches_interests) return false;
  if (f.type && item.type !== f.type) return false;
  if (f.status && item.status !== f.status) return false;
  if (f.source && item.source?.slug !== f.source) return false;
  if (f.topic && !item.topics.some((t) => t.slug === f.topic)) return false;
  if (f.department && item.department !== f.department) return false;
  if (f.campus && campusOf(item.location) !== f.campus) return false;
  if (f.eligibility && item.eligibility !== f.eligibility) return false;
  if (f.minFit > 0 && (item.fit_score === null || item.fit_score < f.minFit)) return false;

  const tokens = f.q.toLowerCase().split(/\s+/).filter(Boolean);
  return tokens.every((t) => haystack.includes(t));
}

/* --------------------------------------------------------------- sorting */

/** Sorts a missing deadline behind a real one, and rolling in between. */
function deadlineRank(item: OpportunityListItem): number {
  if (item.deadline) return 0;
  if (item.deadline_type === "rolling") return 1;
  return 2;
}

function deadlineTime(item: OpportunityListItem): number {
  if (!item.deadline) return Number.POSITIVE_INFINITY;
  const t = new Date(
    item.deadline.length <= 10 ? `${item.deadline}T00:00:00` : item.deadline,
  ).getTime();
  return Number.isNaN(t) ? Number.POSITIVE_INFINITY : t;
}

function byDeadline(a: OpportunityListItem, b: OpportunityListItem): number {
  const ra = deadlineRank(a);
  const rb = deadlineRank(b);
  if (ra !== rb) return ra - rb;
  return deadlineTime(a) - deadlineTime(b);
}

function byFit(a: OpportunityListItem, b: OpportunityListItem): number {
  return (b.fit_score ?? -1) - (a.fit_score ?? -1);
}

function discoveredTime(item: OpportunityListItem): number {
  if (!item.first_seen_at) return 0;
  const t = new Date(item.first_seen_at).getTime();
  return Number.isNaN(t) ? 0 : t;
}

const ACTIONABLE_URGENCY: Urgency[] = ["urgent", "soon"];
const WORKABLE_ELIGIBILITY: EligibilityState[] = ["eligible", "likely_eligible"];

/**
 * "Recommended" is the blended default, in three explicit tiers:
 *
 *   0 — a deadline is close (urgent or soon), you are eligible or likely
 *       eligible, and it has not already been rejected or archived. These are
 *       the only rows where waiting costs you something, so they lead.
 *   1 — everything else still live.
 *   2 — dead weight: overdue, ineligible, rejected, archived. Never hidden,
 *       but never above something you can still act on.
 *
 * Inside a tier: better fit first, then the nearer deadline, then title so the
 * order is stable across renders.
 */
function recommendedTier(item: OpportunityListItem): number {
  const dead =
    item.status === "rejected" ||
    item.status === "archived" ||
    item.urgency === "overdue" ||
    item.deadline_state === "expired" ||
    // You told us you already applied. It stays in the list, but it is no
    // longer work, so it does not compete with what still is.
    item.feedback?.signal === "already_applied";
  if (dead || item.eligibility === "ineligible") return 2;
  if (
    ACTIONABLE_URGENCY.includes(item.urgency) &&
    WORKABLE_ELIGIBILITY.includes(item.eligibility)
  ) {
    return 0;
  }
  return 1;
}

/**
 * Fit, plus the bounded nudge from what you said about *this* row.
 *
 * Mirrors `sort_adjustment` in the API so a reload cannot reorder the list.
 * The score itself is never touched — only its place in this one ordering —
 * which is why "Sort by fit" below still uses the raw number.
 */
function adjustedFit(item: OpportunityListItem): number {
  return (item.fit_score ?? -1) + sortAdjustment(item);
}

function byRecommended(a: OpportunityListItem, b: OpportunityListItem): number {
  const ta = recommendedTier(a);
  const tb = recommendedTier(b);
  if (ta !== tb) return ta - tb;
  const fit = adjustedFit(b) - adjustedFit(a);
  if (fit !== 0) return fit;
  return byDeadline(a, b);
}

function comparator(sort: OpportunityFilters["sort"]) {
  return (a: OpportunityListItem, b: OpportunityListItem): number => {
    let result = 0;
    if (sort === "deadline") result = byDeadline(a, b);
    else if (sort === "fit") result = byFit(a, b);
    else if (sort === "discovered") result = discoveredTime(b) - discoveredTime(a);
    else result = byRecommended(a, b);
    return result !== 0 ? result : a.title.localeCompare(b.title);
  };
}

/* ---------------------------------------------------------------- screen */

export function OpportunitiesClient({
  initialItems,
  facets,
  total,
  savedFocus,
}: {
  initialItems: OpportunityListItem[];
  facets: OpportunityFacets;
  total: number;
  /** The student's last-used view, read from their profile on the server. */
  savedFocus: OpportunityFilters["focus"];
}) {
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const toast = useToast();

  const [items, setItems] = React.useState<OpportunityListItem[]>(initialItems);
  const [filters, setFilters] = React.useState<OpportunityFilters>(() => {
    const fromUrl = parseFilters(searchParams);
    // An explicit ?focus= in the URL wins so a shared link means what it says;
    // otherwise fall back to the view this student last chose.
    return searchParams.get("focus") ? fromUrl : { ...fromUrl, focus: savedFocus };
  });
  // Seeded from the URL: the Overview links to /opportunities?id=<id>, and a
  // panel that only opens on click would make every one of those links a no-op.
  const [selectedId, setSelectedId] = React.useState<string | null>(
    () => searchParams.get("id"),
  );
  const [cursorRaw, setCursor] = React.useState(-1);
  const [importOpen, setImportOpen] = React.useState(false);

  const scrollRef = React.useRef<HTMLDivElement>(null);

  // Mirror filter state into the URL without a navigation, so the view stays
  // linkable and survives a refresh but typing never hits the server.
  React.useEffect(() => {
    const query = filtersToQuery(filters);
    const params = new URLSearchParams(query.startsWith("?") ? query.slice(1) : query);
    if (selectedId) params.set("id", selectedId);
    else params.delete("id");
    const search = params.toString();
    const next = `${pathname}${search ? `?${search}` : ""}`;
    if (`${window.location.pathname}${window.location.search}` !== next) {
      window.history.replaceState(null, "", next);
    }
  }, [filters, pathname, selectedId]);

  const haystacks = React.useMemo(() => {
    const map = new Map<string, string>();
    for (const item of items) map.set(item.id, haystackOf(item));
    return map;
  }, [items]);

  const campusOptions = React.useMemo<FacetOption[]>(() => {
    const counts = countBy(items, (i) => campusOf(i.location));
    return [...counts.entries()]
      .map(([value, count]) => ({ value, label: value, count }))
      .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
  }, [items]);

  const eligibilityOptions = React.useMemo<FacetOption[]>(() => {
    const counts = countBy(items, (i) => i.eligibility);
    return ELIGIBILITY_ORDER.filter((e) => counts.has(e)).map((e) => ({
      value: e,
      label: ELIGIBILITY_LABEL[e],
      count: counts.get(e) ?? 0,
    }));
  }, [items]);

  // Remember the chosen view. Fire-and-forget: a failed write must not block
  // filtering, and the next load simply falls back to the previous value.
  const lastPersisted = React.useRef(savedFocus);
  React.useEffect(() => {
    if (filters.focus === lastPersisted.current) return;
    lastPersisted.current = filters.focus;
    void api.profile
      .update({ preferences: { opportunityFocus: filters.focus } } as never)
      .catch(() => undefined);
  }, [filters.focus]);

  const visible = React.useMemo(() => {
    const filtered = items.filter((item) =>
      matchesFilters(item, filters, haystacks.get(item.id) ?? ""),
    );
    return filtered.sort(comparator(filters.sort));
  }, [items, filters, haystacks]);

  // What each side of the focus toggle would actually show, given every other
  // filter that is on. A count that ignored them would promise the wrong thing.
  const focusCounts = React.useMemo(() => {
    const withFocus = (focus: OpportunityFilters["focus"]) =>
      items.filter((item) =>
        matchesFilters(item, { ...filters, focus }, haystacks.get(item.id) ?? ""),
      ).length;
    return { interests: withFocus("interests"), all: withFocus("all") };
  }, [items, filters, haystacks]);

  // Filtering can shrink the list out from under the keyboard cursor. Clamping
  // during render means there is never a frame pointing at a row that is gone.
  const cursor = cursorRaw >= visible.length ? visible.length - 1 : cursorRaw;

  const selected = React.useMemo(
    () => items.find((i) => i.id === selectedId) ?? null,
    [items, selectedId],
  );

  const patchItem = React.useCallback(
    (id: string, patch: Partial<OpportunityListItem>) => {
      setItems((prev) => prev.map((i) => (i.id === id ? { ...i, ...patch } : i)));
    },
    [],
  );

  const openRow = React.useCallback(
    (id: string) => {
      setSelectedId(id);
      setCursor(visible.findIndex((i) => i.id === id));
    },
    [visible],
  );

  const move = React.useCallback(
    (delta: number) => {
      if (visible.length === 0) return;
      const from = cursor < 0 ? (delta > 0 ? -1 : 0) : cursor;
      const next = Math.max(0, Math.min(visible.length - 1, from + delta));
      setCursor(next);
      // With the panel open the cursor drives it, so you can read straight
      // down the list without going back to the mouse.
      const id = visible[next]?.id;
      if (selectedId !== null && id) setSelectedId(id);
    },
    [visible, cursor, selectedId],
  );

  React.useEffect(() => {
    const id = visible[cursor]?.id;
    if (!id) return;
    scrollRef.current
      ?.querySelector(`[data-oid="${id}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [cursor, visible]);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (importOpen || e.metaKey || e.ctrlKey || e.altKey) return;
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName;
      // Selects and textareas own their arrow keys; the search input does not,
      // so you can type a query and arrow straight into the results.
      if (tag === "SELECT" || tag === "TEXTAREA" || target?.isContentEditable) return;

      if (e.key === "ArrowDown") {
        e.preventDefault();
        move(1);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        move(-1);
      } else if (e.key === "Enter") {
        const id = visible[cursor < 0 ? 0 : cursor]?.id;
        if (id) {
          e.preventDefault();
          openRow(id);
        }
      } else if (e.key === "Escape") {
        if (selectedId) {
          setSelectedId(null);
        } else if (filters.q) {
          setFilters((f) => ({ ...f, q: "" }));
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [importOpen, move, visible, cursor, selectedId, filters.q, openRow]);

  const onImported = React.useCallback(
    (detail: OpportunityDetail) => {
      setItems((prev) => {
        const without = prev.filter((i) => i.id !== detail.id);
        return [detail, ...without];
      });
      setSelectedId(detail.id);
      if (!matchesFilters(detail, filters, haystackOf(detail))) {
        toast.push("Imported — your current filters hide it, so only the panel shows it.");
      } else {
        toast.push("Imported", "success");
      }
    },
    [filters, toast],
  );

  // Every count on this screen describes the side of the confidence gate you
  // are actually looking at. Counting across both would mean "12 of 15 shown"
  // where the three missing rows are ones the product refuses to recommend.
  const inScope = items.filter((i) => i.confidence_state === filters.confidence);
  const held = filters.confidence === "held";
  const filtered = visible.length !== inScope.length;

  // How many rows this view is hiding *only* because they expired — measured
  // with every other filter still applied, so the number is a promise about
  // what "Show them" would actually add.
  const expiredHidden = React.useMemo(() => {
    if (filters.showExpired) return 0;
    return items.filter(
      (item) =>
        hiddenAsExpired(item) &&
        matchesFilters(
          item,
          { ...filters, showExpired: true },
          haystacks.get(item.id) ?? "",
        ),
    ).length;
  }, [items, filters, haystacks]);

  // Same measurement for rows you put away yourself: with every other filter
  // still applied, so "Show them" adds exactly this many.
  const hiddenByYou = React.useMemo(() => {
    if (filters.showHidden) return 0;
    return items.filter(
      (item) =>
        isHidden(item) &&
        matchesFilters(
          item,
          { ...filters, showHidden: true },
          haystacks.get(item.id) ?? "",
        ),
    ).length;
  }, [items, filters, haystacks]);

  const expiredNote = expiredHidden > 0 ? ` · ${expiredHidden} expired hidden` : "";
  const hiddenNote = hiddenByYou > 0 ? ` · ${hiddenByYou} hidden by you` : "";
  const description = held
    ? `${visible.length} held back — not recommended`
    : inScope.length === 0
      ? "Nothing discovered yet"
      : filtered
        ? `${visible.length} of ${inScope.length} shown${hiddenNote}${expiredNote}${total > inScope.length ? ` · ${total} total` : ""}`
        : `${inScope.length} tracked${total > inScope.length ? ` of ${total}` : ""}`;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader title="Opportunities" description={description}>
        <FilterBar
          filters={filters}
          onChange={setFilters}
          facets={facets}
          campusOptions={campusOptions}
          eligibilityOptions={eligibilityOptions}
          onImport={() => setImportOpen(true)}
          relevantCount={focusCounts.interests}
          totalCount={focusCounts.all}
        />
      </PageHeader>

      <div ref={scrollRef} className="scrollbar-thin min-h-0 flex-1 overflow-y-auto">
        {held && (
          // Stated in full at the top of the view rather than implied by a
          // label, because the student is about to read rows the product
          // deliberately declined to recommend and deserves to know why.
          <p className="border-b border-[var(--border-subtle)] bg-[var(--bg-subtle)] px-5 py-2 text-xs leading-relaxed text-[var(--text-secondary)]">
            These are postings Trellis found but could barely read — no deadline, pay, hours,
            qualifications or way to apply came off the page. Nothing was deleted and nothing
            was guessed; they are simply not scored and not recommended. If a later run reads
            one properly it moves back into your list on its own.
          </p>
        )}
        {inScope.length === 0 ? (
          held ? (
            <EmptyState
              title="Nothing is being held back"
              body="Every opportunity Trellis has found extracted well enough to stand on its own. This view fills up only when a page reads too thinly to recommend."
              action={
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setFilters({ ...filters, confidence: "ok" })}
                >
                  Back to your list
                </Button>
              }
            />
          ) : (
          <EmptyState
            title="No opportunities yet"
            body="Nothing has been discovered for your profile so far. Run a search from the Overview page, or paste the URL of a posting you already found."
            action={
              <Button variant="primary" size="sm" onClick={() => setImportOpen(true)}>
                Import URL
              </Button>
            }
          />
          )
        ) : visible.length === 0 ? (
          <EmptyState
            title="Nothing matches these filters"
            body={`All ${inScope.length} opportunities were filtered out. Loosen a filter — the fit threshold and the eligibility filter are the two that hide the most.`}
            action={
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setFilters({ ...DEFAULT_FILTERS, sort: filters.sort })}
              >
                Clear all filters
              </Button>
            }
          />
        ) : (
          <>
            <table className="hidden w-full table-fixed md:table">
              <thead>
                <tr>
                  <Th className="w-20">Score</Th>
                  <Th>Opportunity</Th>
                  <Th className="w-32">Type</Th>
                  <Th className="w-40">Deadline</Th>
                  <Th className="w-28">Status</Th>
                  <Th className="w-24">Source</Th>
                  <Th className="w-[116px] text-right">
                    <span className="sr-only">Your call on this one</span>
                  </Th>
                </tr>
              </thead>
              <tbody>
                {visible.map((item, index) => (
                  <Row
                    key={item.id}
                    item={item}
                    selected={item.id === selectedId}
                    cursored={index === cursor}
                    showRelevance={filters.focus === "all"}
                    onOpen={() => openRow(item.id)}
                    onPatch={patchItem}
                  />
                ))}
              </tbody>
            </table>

            <ul className="divide-y divide-[var(--border-subtle)] md:hidden">
              {visible.map((item) => (
                <CompactRow
                  key={item.id}
                  item={item}
                  selected={item.id === selectedId}
                  onOpen={() => openRow(item.id)}
                  onPatch={patchItem}
                />
              ))}
            </ul>
          </>
        )}

        {!held && (hiddenByYou > 0 || filters.showHidden) && (
          // The count is stated where the omission happens, with one click to
          // reverse it. A list that silently drops rows is the thing this
          // product is not allowed to be.
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-[var(--border-subtle)] bg-[var(--bg-subtle)] px-5 py-2">
            <span className="text-xs text-[var(--text-tertiary)]">
              {filters.showHidden
                ? "Showing the opportunities you hid. Each one still carries the tag that says so, and clearing it puts the row back."
                : `${hiddenByYou} opportunit${hiddenByYou === 1 ? "y" : "ies"} hidden by you. Nothing was deleted, and discovery will not resurface ${hiddenByYou === 1 ? "it" : "them"} as new.`}
            </span>
            <Button
              variant="link"
              size="xs"
              onClick={() => setFilters({ ...filters, showHidden: !filters.showHidden })}
            >
              {filters.showHidden ? "Hide them again" : "Show them"}
            </Button>
          </div>
        )}

        {!held && (expiredHidden > 0 || filters.showExpired) && (
          // The omission is stated where it happens, at the end of the list,
          // with the exact count and one click to undo it. Hiding something
          // without saying so is the thing this product is not allowed to do.
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-[var(--border-subtle)] bg-[var(--bg-subtle)] px-5 py-2">
            <span className="text-xs text-[var(--text-tertiary)]">
              {filters.showExpired
                ? "Showing opportunities whose deadline has already passed. They are kept for the record — nothing is ever deleted."
                : `${expiredHidden} opportunit${expiredHidden === 1 ? "y" : "ies"} ${
                    expiredHidden === 1 ? "is" : "are"
                  } hidden because the deadline has passed. Anything you saved or applied to is still shown.`}
            </span>
            <Button
              variant="link"
              size="xs"
              onClick={() => setFilters({ ...filters, showExpired: !filters.showExpired })}
            >
              {filters.showExpired ? "Hide expired" : "Show them"}
            </Button>
          </div>
        )}
      </div>

      {selected && (
        <OpportunityPanel
          item={selected}
          onClose={() => setSelectedId(null)}
          onPatch={patchItem}
        />
      )}

      {importOpen && (
        <ImportUrlDialog onClose={() => setImportOpen(false)} onImported={onImported} />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ rows */

function Th({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <th
      scope="col"
      className={cn(
        "sticky top-0 z-10 h-8 bg-[var(--bg)] px-3 text-left align-middle",
        "text-2xs font-medium uppercase tracking-[0.05em] text-[var(--text-tertiary)]",
        "shadow-[inset_0_-1px_0_var(--border)]",
        className,
      )}
    >
      {children}
    </th>
  );
}

function subtitleOf(item: OpportunityListItem): string {
  return [item.lab_name, item.organization ?? item.department, item.pi_name]
    .filter((v): v is string => Boolean(v))
    .filter((v, i, all) => all.indexOf(v) === i)
    .join(" · ");
}

function Row({
  item,
  selected,
  cursored,
  showRelevance,
  onOpen,
  onPatch,
}: {
  item: OpportunityListItem;
  selected: boolean;
  cursored: boolean;
  showRelevance: boolean;
  onOpen: () => void;
  onPatch: (id: string, patch: Partial<OpportunityListItem>) => void;
}) {
  return (
    <tr
      data-oid={item.id}
      aria-current={selected ? "true" : undefined}
      onClick={onOpen}
      className={cn(
        "group h-11 cursor-pointer border-b border-[var(--border-subtle)]",
        "transition-colors duration-100",
        selected
          ? "bg-[var(--bg-selected)]"
          : cursored
            ? "bg-[var(--bg-hover)]"
            : "hover:bg-[var(--bg-hover)]",
      )}
    >
      <td
        className={cn(
          "relative px-3",
          selected &&
            "before:absolute before:inset-y-0 before:left-0 before:w-0.5 before:bg-[var(--accent)] before:content-['']",
        )}
      >
        {item.confidence_state === "held" ? (
          // A held row carries no score by construction: its match was removed
          // when it was held, because a fit number computed from a page we
          // could not read is a confident-looking guess.
          <Tooltip content="Not scored — too little came off the page to judge fit against you.">
            <span className="text-2xs uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
              Not scored
            </span>
          </Tooltip>
        ) : (
          <ScoreMeter score={item.fit_score} confidence={item.fit_confidence} />
        )}
      </td>

      <td className="px-3">
        <div className="flex items-center gap-1.5">
          {item.is_new && (
            <Tooltip content="First seen in the most recent discovery run.">
              <span className="size-1.5 shrink-0 rounded-full bg-[var(--accent)]" />
            </Tooltip>
          )}
          <span className="truncate text-sm font-medium leading-[18px] text-[var(--text-primary)]">
            {item.title}
          </span>
        </div>
        <div className="flex items-center gap-1.5 truncate text-xs leading-[16px] text-[var(--text-tertiary)]">
          <span className="truncate">
            {item.confidence_state === "held"
              ? item.confidence_reason || subtitleOf(item) || "—"
              : subtitleOf(item) || "—"}
          </span>
          <SourceStatusBadge
            status={item.source_status}
            checkedAt={item.source_status_at}
            compact
          />
          {item.relevance_reason && showRelevance && (
            // Makes the focus filter interrogable: you can see why a row is here
            // rather than trusting that it belongs.
            <Tooltip content={item.relevance_reason}>
              <span className="shrink-0 rounded-[var(--radius-xs)] bg-[var(--accent-soft)] px-1 text-[10px] font-medium text-[var(--color-accent-700)]">
                match
              </span>
            </Tooltip>
          )}
        </div>
      </td>

      <td className="px-3">
        <TypeTag type={item.type} />
      </td>

      <td className="px-3">
        <DeadlineCell
          deadline={item.deadline}
          type={item.deadline_type}
          state={item.deadline_state}
          urgency={item.urgency}
          days={item.days_until_deadline}
          certainty={item.deadline_certainty}
        />
      </td>

      <td className="px-3">
        <StatusPill status={item.status} />
      </td>

      <td className="px-3">
        <span className="block truncate text-xs text-[var(--text-tertiary)]">
          {hostOf(item.source_url) || item.source?.name || "—"}
        </span>
      </td>

      <td className="px-3 text-right">
        <div className="flex justify-end">
          <RowFeedbackControls item={item} onPatch={onPatch} />
        </div>
      </td>
    </tr>
  );
}

function CompactRow({
  item,
  selected,
  onOpen,
  onPatch,
}: {
  item: OpportunityListItem;
  selected: boolean;
  onOpen: () => void;
  onPatch: (id: string, patch: Partial<OpportunityListItem>) => void;
}) {
  return (
    <li data-oid={item.id} className="flex items-center">
      <button
        onClick={onOpen}
        aria-current={selected ? "true" : undefined}
        className={cn(
          "flex min-w-0 flex-1 items-center gap-3 px-4 py-2.5 text-left",
          selected
            ? "border-l-2 border-[var(--accent)] bg-[var(--bg-selected)] pl-[14px]"
            : "active:bg-[var(--bg-hover)]",
        )}
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            {item.is_new && (
              <span className="size-1.5 shrink-0 rounded-full bg-[var(--accent)]" aria-hidden />
            )}
            <span className="truncate text-sm font-medium text-[var(--text-primary)]">
              {item.title}
            </span>
          </div>
          <div className="mt-1 flex items-center gap-2 overflow-hidden">
            <span className="truncate text-xs text-[var(--text-tertiary)]">
              {subtitleOf(item) || hostOf(item.source_url)}
            </span>
            <SourceStatusBadge
              status={item.source_status}
              checkedAt={item.source_status_at}
              compact
            />
            <span className="shrink-0">
              <DeadlineCell
                deadline={item.deadline}
                type={item.deadline_type}
                state={item.deadline_state}
                urgency={item.urgency}
                days={item.days_until_deadline}
                certainty={item.deadline_certainty}
                compact
              />
            </span>
          </div>
        </div>
        {item.confidence_state === "held" ? (
          <span className="shrink-0 text-2xs uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
            Not scored
          </span>
        ) : (
          <ScoreMeter score={item.fit_score} confidence={item.fit_confidence} />
        )}
      </button>
      {/* Outside the button on purpose: its undo is itself a button, and one
          may never be nested inside another. */}
      {item.feedback && (
        <span className="shrink-0 pr-4">
          <RowFeedbackControls item={item} onPatch={onPatch} compact />
        </span>
      )}
    </li>
  );
}
