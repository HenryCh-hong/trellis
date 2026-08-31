"use client";

import * as React from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";

export interface FacetItem {
  value: string;
  label: string;
  count: number;
  hint?: string;
}

export interface FacetGroup {
  key: string;
  label: string;
  items: FacetItem[];
  /** Shown instead of the list when the group has nothing to offer. */
  empty?: React.ReactNode;
  /** Groups longer than this collapse behind a "Show all" toggle. */
  limit?: number;
}

/**
 * Browse rail.
 *
 * Counts are recomputed against every *other* active filter, so a facet never
 * promises results it cannot deliver: pick a department and the topic counts
 * immediately describe that department alone.
 */
export function BrowseRail({
  groups,
  total,
  selected,
  onSelect,
  onClear,
}: {
  groups: FacetGroup[];
  total: number;
  selected: Record<string, string>;
  onSelect: (group: string, value: string) => void;
  onClear: () => void;
}) {
  const anySelected = Object.values(selected).some(Boolean);

  return (
    <aside
      aria-label="Browse research leads"
      className="hidden w-56 shrink-0 flex-col border-r border-[var(--border)] bg-[var(--bg-subtle)] lg:flex"
    >
      <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-2 py-3">
        <RailRow
          label="All leads"
          count={total}
          active={!anySelected}
          onClick={onClear}
        />
        {groups.map((group) => (
          <RailGroup
            key={group.key}
            group={group}
            selected={selected[group.key] ?? ""}
            onSelect={(value) => onSelect(group.key, value)}
          />
        ))}
      </div>
    </aside>
  );
}

function RailGroup({
  group,
  selected,
  onSelect,
}: {
  group: FacetGroup;
  selected: string;
  onSelect: (value: string) => void;
}) {
  const [expanded, setExpanded] = React.useState(false);
  const limit = group.limit ?? group.items.length;
  const overflowing = group.items.length > limit;
  const shown =
    expanded || !overflowing
      ? group.items
      : // Keep the active row visible even when it sits past the fold.
        dedupe([
          ...group.items.slice(0, limit),
          ...group.items.filter((i) => i.value === selected),
        ]);

  return (
    <section className="mt-4">
      <h3 className="px-2 pb-1 text-2xs font-semibold uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
        {group.label}
      </h3>
      {group.items.length === 0 && group.empty ? (
        <div className="px-2 py-1 text-2xs leading-relaxed text-[var(--text-tertiary)]">
          {group.empty}
        </div>
      ) : (
        <>
          {shown.map((item) => (
            <RailRow
              key={item.value}
              label={item.label}
              hint={item.hint}
              count={item.count}
              active={selected === item.value}
              muted={item.count === 0}
              onClick={() => onSelect(selected === item.value ? "" : item.value)}
            />
          ))}
          {overflowing && (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="mt-0.5 px-2 py-1 text-2xs text-[var(--text-tertiary)] transition-colors duration-100 hover:text-[var(--text-primary)]"
            >
              {expanded ? "Show fewer" : `Show all ${group.items.length}`}
            </button>
          )}
        </>
      )}
    </section>
  );
}

function RailRow({
  label,
  hint,
  count,
  active,
  muted,
  onClick,
}: {
  label: string;
  hint?: string;
  count: number;
  active: boolean;
  muted?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      title={hint ?? label}
      className={cn(
        "flex h-7 w-full items-center justify-between gap-2 rounded-[var(--radius-sm)] px-2 text-left",
        "text-xs transition-colors duration-100",
        active
          ? "bg-[var(--bg-selected)] font-medium text-[var(--accent)]"
          : muted
            ? "text-[var(--text-disabled)] hover:bg-[var(--bg-hover)]"
            : "text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]",
      )}
    >
      <span className="truncate">{label}</span>
      <span className={cn("tnum shrink-0 text-2xs", active ? "text-[var(--accent)]" : "text-[var(--text-tertiary)]")}>
        {count}
      </span>
    </button>
  );
}

/** The link the rail shows when the student has told us nothing to match on. */
export function RailProfileNote() {
  return (
    <>
      Add what you want to work on to your{" "}
      <Link href="/profile" className="text-[var(--accent)] hover:underline">
        profile
      </Link>{" "}
      and leads will group by it.
    </>
  );
}

function dedupe(items: FacetItem[]): FacetItem[] {
  const seen = new Set<string>();
  return items.filter((i) => (seen.has(i.value) ? false : (seen.add(i.value), true)));
}
