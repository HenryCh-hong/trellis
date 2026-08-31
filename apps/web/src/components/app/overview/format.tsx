/**
 * Small formatters shared by the Overview sections.
 *
 * They exist so that a missing value reads the same way in every block — an
 * opportunity with no stated organisation says so once, here, rather than
 * rendering an empty cell in one table and "null" in another.
 */

import type { OpportunityListItem, ResearchLead } from "@/lib/types";
import { hostOf, relativeDays } from "@/lib/utils";

export function firstName(displayName: string | null): string | null {
  if (!displayName) return null;
  const first = displayName.trim().split(/\s+/)[0];
  return first ? first : null;
}

/** "Chemistry Dept · Nolan Lab" — whatever of the two the source actually gave. */
export function orgLine(o: OpportunityListItem): string {
  // A lab lead usually has organization == lab_name; joining them printed the
  // lab twice on every card.
  const seen = new Set<string>();
  const parts = [o.lab_name, o.organization, o.pi_name].filter(
    (p): p is string => {
      if (!p || !p.trim()) return false;
      const key = p.trim().toLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    },
  );
  if (parts.length) return parts.slice(0, 2).join(" · ");
  if (o.pi_name) return o.pi_name;
  if (o.department) return o.department;
  return "Organisation not stated";
}

export function leadHeading(lead: ResearchLead): string {
  return lead.lab?.name ?? lead.faculty.name;
}

export function leadSubline(lead: ResearchLead): string {
  const f = lead.faculty;
  const parts = lead.lab ? [f.name, f.title] : [f.title, f.department];
  const kept = parts.filter((p): p is string => Boolean(p && p.trim()));
  return kept.length ? kept.join(" · ") : f.university;
}

/** "today" / "3 days ago" from an ISO timestamp. */
export function sinceLabel(iso: string | null): string {
  if (!iso) return "Unknown";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "Unknown";
  const days = Math.floor((Date.now() - t) / 86_400_000);
  return relativeDays(-days);
}

export function sourceLabel(o: OpportunityListItem): string {
  return hostOf(o.source_url) || o.source?.name || "Source unknown";
}

/** Deadline first, undated last — the order the student actually cares about. */
export function byDeadline(a: OpportunityListItem, b: OpportunityListItem): number {
  if (!a.deadline && !b.deadline) return (b.fit_score ?? 0) - (a.fit_score ?? 0);
  if (!a.deadline) return 1;
  if (!b.deadline) return -1;
  return a.deadline.localeCompare(b.deadline);
}

export function byFit(a: OpportunityListItem, b: OpportunityListItem): number {
  return (b.fit_score ?? -1) - (a.fit_score ?? -1);
}

/** Newest first — an item seen today is the one worth a second look. */
export function byFirstSeen(a: OpportunityListItem, b: OpportunityListItem): number {
  if (!a.first_seen_at && !b.first_seen_at) return 0;
  if (!a.first_seen_at) return 1;
  if (!b.first_seen_at) return -1;
  return b.first_seen_at.localeCompare(a.first_seen_at);
}
