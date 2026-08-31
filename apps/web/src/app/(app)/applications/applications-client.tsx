"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { DeadlineCell, StatusPill, statusLabel } from "@/components/app/indicators";
import { PageHeader } from "@/components/app/page-header";
import { Select } from "@/components/ui/input";
import { Badge, EmptyState, SegmentedControl } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import type { ApplicationKit, OpportunityStatus } from "@/lib/types";
import { cn, formatDateTime } from "@/lib/utils";

/** Pipeline order. Statuses not listed never appear as a group. */
const STAGES: OpportunityStatus[] = [
  "preparing",
  "ready_to_apply",
  "applying",
  "submitted",
  "interview",
  "offer",
  "rejected",
  "archived",
];

// Moving a status is a Select, not drag-and-drop: it is keyboard-reachable,
// works on a phone, and cannot fire from a stray drag.
const MOVE_TARGETS: Record<string, OpportunityStatus[]> = {
  preparing: ["ready_to_apply", "archived"],
  ready_to_apply: ["applying", "submitted", "preparing", "archived"],
  applying: ["submitted", "archived"],
  submitted: ["interview", "offer", "rejected", "archived"],
  interview: ["offer", "rejected", "archived"],
  offer: ["archived"],
  rejected: ["archived"],
  // Archiving is reversible; resuming lands in Preparing.
  archived: ["preparing"],
};

export function ApplicationsClient({ initial }: { initial: ApplicationKit[] }) {
  const router = useRouter();
  const params = useSearchParams();
  const toast = useToast();

  const [kits, setKits] = React.useState(initial);
  const [view, setView] = React.useState<"list" | "board">("list");
  const [busy, setBusy] = React.useState<string | null>(null);
  const [collapsed, setCollapsed] = React.useState<Set<string>>(new Set());

  const statusFilter = params.get("status");

  const shown = React.useMemo(
    () => (statusFilter ? kits.filter((k) => k.status === statusFilter) : kits),
    [kits, statusFilter],
  );

  const grouped = React.useMemo(() => {
    const map = new Map<OpportunityStatus, ApplicationKit[]>();
    for (const stage of STAGES) map.set(stage, []);
    for (const kit of shown) map.get(kit.status as OpportunityStatus)?.push(kit);
    return STAGES.map((s) => [s, map.get(s) ?? []] as const).filter(([, v]) => v.length > 0);
  }, [shown]);

  async function move(kit: ApplicationKit, status: string) {
    setBusy(kit.id);
    const previous = kits;
    setKits((cur) =>
      cur.map((k) => (k.id === kit.id ? { ...k, status: status as OpportunityStatus } : k)),
    );
    try {
      const updated = await api.applications.update(kit.id, { status });
      setKits((cur) => cur.map((k) => (k.id === kit.id ? updated : k)));
      toast.push(`Moved to ${statusLabel(status as OpportunityStatus)}`, "success");
      router.refresh();
    } catch (error) {
      setKits(previous);
      toast.push(error instanceof Error ? error.message : "Could not move that", "error");
    } finally {
      setBusy(null);
    }
  }

  if (kits.length === 0) {
    return (
      <>
        <PageHeader title="Applications" />
        <EmptyState
          className="py-24"
          title="No applications yet"
          body="When you prepare an application, its kit lands here — the recommended resume, the documents you still need, and the questions only you can answer."
          action={
            <Link
              href="/opportunities"
              className="text-xs font-medium text-[var(--accent)] hover:underline"
            >
              Browse opportunities
            </Link>
          }
        />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Applications"
        description={`${kits.length} in your pipeline`}
        actions={
          <div className="flex items-center gap-2">
            {statusFilter && (
              <button
                onClick={() => router.replace("/applications")}
                className="text-xs text-[var(--accent)] hover:underline"
              >
                Clear filter
              </button>
            )}
            <SegmentedControl
              options={[
                { value: "list", label: "List" },
                { value: "board", label: "Board" },
              ]}
              value={view}
              onChange={setView}
            />
          </div>
        }
      />

      <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto">
        {view === "board" ? (
          <div className="scrollbar-thin flex gap-3 overflow-x-auto p-5">
            {grouped.map(([stage, items]) => (
              <section key={stage} className="w-[260px] shrink-0">
                <div className="mb-2 flex items-center gap-2">
                  <StatusPill status={stage} />
                  <span className="text-xs tabular-nums text-[var(--text-tertiary)]">
                    {items.length}
                  </span>
                </div>
                <div className="space-y-2">
                  {items.map((kit) => (
                    <Link
                      key={kit.id}
                      href={`/applications/${kit.id}`}
                      className="block rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg)] p-2.5 transition-colors hover:border-[var(--border-strong)]"
                    >
                      <div className="line-clamp-2 text-xs font-medium">
                        {kit.opportunity.title}
                      </div>
                      <div className="mt-1 truncate text-2xs text-[var(--text-tertiary)]">
                        {kit.opportunity.organization}
                      </div>
                      {kit.blocking.length > 0 && (
                        <div className="mt-1.5">
                          <Badge tone="warn">{kit.blocking.length} to do</Badge>
                        </div>
                      )}
                    </Link>
                  ))}
                </div>
              </section>
            ))}
          </div>
        ) : (
          <div className="p-5">
            {grouped.map(([stage, items]) => {
              const isCollapsed = collapsed.has(stage);
              return (
                <section key={stage} className="mb-6">
                  <button
                    onClick={() =>
                      setCollapsed((cur) => {
                        const next = new Set(cur);
                        if (next.has(stage)) next.delete(stage);
                        else next.add(stage);
                        return next;
                      })
                    }
                    className="mb-2 flex items-center gap-2"
                  >
                    <svg
                      className={cn(
                        "size-3 text-[var(--text-tertiary)] transition-transform",
                        isCollapsed && "-rotate-90",
                      )}
                      viewBox="0 0 12 12"
                      fill="none"
                      aria-hidden
                    >
                      <path
                        d="M3 4.5 6 7.5 9 4.5"
                        stroke="currentColor"
                        strokeWidth="1.4"
                        strokeLinecap="round"
                      />
                    </svg>
                    <StatusPill status={stage} />
                    <span className="text-xs tabular-nums text-[var(--text-tertiary)]">
                      {items.length}
                    </span>
                  </button>

                  {!isCollapsed && (
                    <div className="overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border)]">
                      <table className="w-full text-left">
                        <thead className="bg-[var(--bg-subtle)]">
                          <tr className="text-2xs uppercase tracking-[0.04em] text-[var(--text-tertiary)]">
                            <th className="px-3 py-2 font-medium">Opportunity</th>
                            <th className="hidden px-3 py-2 font-medium md:table-cell">Deadline</th>
                            <th className="hidden px-3 py-2 font-medium lg:table-cell">Resume</th>
                            <th className="px-3 py-2 font-medium">Blockers</th>
                            <th className="hidden px-3 py-2 font-medium xl:table-cell">Updated</th>
                            <th className="px-3 py-2 font-medium">Move</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-[var(--border-subtle)]">
                          {items.map((kit) => (
                            <tr key={kit.id} className="hover:bg-[var(--bg-hover)]">
                              <td className="px-3 py-2">
                                <Link
                                  href={`/applications/${kit.id}`}
                                  className="block max-w-[380px] truncate text-xs font-medium hover:text-[var(--accent)]"
                                >
                                  {kit.opportunity.title}
                                </Link>
                                <span className="truncate text-2xs text-[var(--text-tertiary)]">
                                  {kit.opportunity.organization}
                                </span>
                              </td>
                              <td className="hidden px-3 py-2 md:table-cell">
                                <DeadlineCell
                                  deadline={kit.opportunity.deadline}
                                  type={kit.opportunity.deadline_type}
                                  state={kit.opportunity.deadline_state}
                                  urgency={kit.opportunity.urgency}
                                  days={kit.opportunity.days_until_deadline}
                                  compact
                                />
                              </td>
                              <td className="hidden max-w-[160px] truncate px-3 py-2 text-xs text-[var(--text-secondary)] lg:table-cell">
                                {kit.resume_label ?? "—"}
                              </td>
                              <td className="px-3 py-2">
                                {kit.blocking.length === 0 ? (
                                  <Badge tone="success">Ready</Badge>
                                ) : (
                                  <span
                                    className="text-xs text-[var(--color-warn-700)]"
                                    title={kit.blocking.join(" · ")}
                                  >
                                    {kit.blocking.length} · {kit.blocking[0]}
                                  </span>
                                )}
                              </td>
                              <td className="hidden whitespace-nowrap px-3 py-2 text-2xs text-[var(--text-tertiary)] xl:table-cell">
                                {formatDateTime(kit.prepared_at)}
                              </td>
                              <td className="px-3 py-2">
                                <Select
                                  aria-label={`Move ${kit.opportunity.title}`}
                                  value=""
                                  disabled={busy === kit.id || !MOVE_TARGETS[kit.status]?.length}
                                  onChange={(e) => e.target.value && move(kit, e.target.value)}
                                  className="h-7 w-[124px] text-xs"
                                >
                                  <option value="">Move to…</option>
                                  {(MOVE_TARGETS[kit.status] ?? []).map((s) => (
                                    <option key={s} value={s}>
                                      {statusLabel(s)}
                                    </option>
                                  ))}
                                </Select>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </section>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}
