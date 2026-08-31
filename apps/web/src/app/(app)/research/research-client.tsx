"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/app/page-header";
import { BrowseRail, RailProfileNote, type FacetGroup } from "@/components/app/research/browse-rail";
import {
  SORT_OPTIONS,
  slugify,
  compareLeads,
  interestSlug,
  isLeadSort,
  isLeadState,
  leadSearchText,
  slugsOverlap,
} from "@/components/app/research/format";
import { LEAD_STATE_LABEL } from "@/components/app/indicators";
import { LeadCard } from "@/components/app/research/lead-card";
import { LeadTable } from "@/components/app/research/lead-table";
import { Input, Select } from "@/components/ui/input";
import { EmptyState, SegmentedControl } from "@/components/ui/primitives";
import type { LeadSort } from "@/components/app/research/format";
import type {
  ProfileInterestItem,
  ResearchFacets,
  ResearchLead,
  StudentProfile,
} from "@/lib/types";

type View = "cards" | "table";

const GROUPS = ["state", "department", "topic", "interest"] as const;


/**
 * Does this lead touch that interest?
 *
 * `lead.overlap` is the server's answer, already widened across related topics
 * and labelled with the student's own wording — so the rail counts agree with
 * the "why it matches" line on the card. Raw topic slugs are only a fallback
 * for leads the server found no overlap for.
 */
function touchesInterest(lead: ResearchLead, interest: ProfileInterestItem): boolean {
  // The server labels every overlap entry with the student's OWN wording, so an
  // exact label comparison is the reliable test. Slug comparison is not: the
  // interest may be stored against a canonical slug (multimodal-learning) while
  // its label slugifies to something else (multimodal-ai).
  if (lead.overlap.some((o) => o.topic === interest.label)) return true;
  const slug = interestSlug(interest);
  return (
    lead.overlap.some((o) => slugsOverlap(slugify(o.topic), slug)) ||
    lead.topics.some((t) => slugsOverlap(t.slug, slug))
  );
}

export function ResearchClient({
  leads,
  facets,
  profile,
}: {
  leads: ResearchLead[];
  facets: ResearchFacets;
  profile: StudentProfile | null;
}) {
  const router = useRouter();
  const params = useSearchParams();

  const [query, setQuery] = React.useState("");
  const [view, setView] = React.useState<View>("cards");

  const selected = React.useMemo(() => {
    const out: Record<string, string> = {};
    for (const key of GROUPS) out[key] = params.get(key) ?? "";
    return out;
  }, [params]);

  const sortParam = params.get("sort") ?? "match";
  const sort: LeadSort = isLeadSort(sortParam) ? sortParam : "match";

  const setParam = React.useCallback(
    (key: string, value: string) => {
      const next = new URLSearchParams(params.toString());
      if (!value || next.get(key) === value) next.delete(key);
      else next.set(key, value);
      router.replace(next.toString() ? `/research?${next}` : "/research", { scroll: false });
    },
    [params, router],
  );

  const clearAll = React.useCallback(() => {
    router.replace("/research", { scroll: false });
  }, [router]);

  /**
   * Filters are applied in two passes so each facet's counts can be computed
   * against every *other* active filter. A count that promised results it could
   * not deliver would make the rail worse than no rail at all.
   */
  const matches = React.useCallback(
    (lead: ResearchLead, ignore: string | null) => {
      if (selected.state && ignore !== "state" && lead.lead_state !== selected.state) return false;
      if (
        selected.department &&
        ignore !== "department" &&
        lead.faculty.department !== selected.department
      ) {
        return false;
      }
      if (
        selected.topic &&
        ignore !== "topic" &&
        !lead.topics.some((t) => t.slug === selected.topic)
      ) {
        return false;
      }
      if (selected.interest && ignore !== "interest") {
        const chosen = (profile?.interests ?? []).find(
          (i) => interestSlug(i) === selected.interest,
        );
        if (!chosen || !touchesInterest(lead, chosen)) return false;
      }
      return true;
    },
    [selected, profile],
  );

  const visible = React.useMemo(() => {
    const needle = query.trim().toLowerCase();
    return leads
      .filter((lead) => matches(lead, null))
      .filter((lead) => !needle || leadSearchText(lead).includes(needle))
      .sort(compareLeads(sort));
  }, [leads, matches, query, sort]);

  const countFor = React.useCallback(
    (group: string, predicate: (lead: ResearchLead) => boolean) =>
      leads.filter((lead) => matches(lead, group) && predicate(lead)).length,
    [leads, matches],
  );

  const groups: FacetGroup[] = React.useMemo(() => {
    const interests = profile?.interests ?? [];
    return [
      {
        key: "state",
        label: "Opportunity state",
        items: facets.states.map((s) => ({
          value: s.value,
          label: isLeadState(s.value) ? LEAD_STATE_LABEL[s.value] : s.value,
          count: countFor("state", (l) => l.lead_state === s.value),
        })),
      },
      {
        key: "interest",
        label: "Your interests",
        items: interests.map((i) => {
          const slug = interestSlug(i);
          return {
            value: slug,
            label: i.label,
            count: countFor("interest", (l) => touchesInterest(l, i)),
          };
        }),
        empty: <RailProfileNote />,
      },
      {
        key: "department",
        label: "Department",
        items: facets.departments.map((d) => ({
          value: d.value,
          label: d.label ?? d.value,
          count: countFor("department", (l) => l.faculty.department === d.value),
        })),
        limit: 8,
      },
      {
        key: "topic",
        label: "Topic",
        items: facets.topics.map((t) => ({
          value: t.value,
          label: t.label ?? t.value,
          count: countFor("topic", (l) => l.topics.some((x) => x.slug === t.value)),
        })),
        limit: 10,
      },
    ];
  }, [facets, profile, countFor]);

  return (
    <>
      <PageHeader
        title="Research"
        description={`${leads.length} labs and professors, ranked by what they are working on now`}
        actions={
          <div className="flex items-center gap-2">
            <Select
              aria-label="Sort research leads"
              value={sort}
              onChange={(e) => setParam("sort", e.target.value)}
              className="w-[168px]"
            >
              {SORT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
            <SegmentedControl
              options={[
                { value: "cards", label: "Cards" },
                { value: "table", label: "Table" },
              ]}
              value={view}
              onChange={setView}
            />
          </div>
        }
      >
        <div className="border-t border-[var(--border-subtle)] px-5 py-2">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search labs, professors, topics or recent work…"
            aria-label="Search research leads"
            className="max-w-[420px]"
          />
        </div>
      </PageHeader>

      <div className="flex min-h-0 flex-1">
        <BrowseRail
          groups={groups}
          total={visible.length}
          selected={selected}
          onSelect={setParam}
          onClear={clearAll}
        />

        <div className="scrollbar-thin min-w-0 flex-1 overflow-y-auto">
          {visible.length === 0 ? (
            <EmptyState
              className="py-24"
              title={leads.length === 0 ? "No research leads yet" : "Nothing matches those filters"}
              body={
                leads.length === 0
                  ? "Tell us what you want to work on. We'll find professors, labs, recent projects, and potential undergraduate research leads."
                  : "Try clearing a filter, or widen your search. Every lead here is backed by evidence we could actually read."
              }
              action={
                leads.length === 0 ? (
                  <a
                    href="/profile"
                    className="text-xs font-medium text-[var(--accent)] hover:underline"
                  >
                    Add your research interests
                  </a>
                ) : (
                  <button
                    onClick={clearAll}
                    className="text-xs font-medium text-[var(--accent)] hover:underline"
                  >
                    Clear all filters
                  </button>
                )
              }
            />
          ) : view === "table" ? (
            <LeadTable leads={visible} />
          ) : (
            <div className="grid gap-3 p-5 md:grid-cols-2 2xl:grid-cols-3">
              {visible.map((lead) => (
                <LeadCard key={lead.opportunity_id} lead={lead} />
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
