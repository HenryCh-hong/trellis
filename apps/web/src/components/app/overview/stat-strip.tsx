import Link from "next/link";
import type { Overview } from "@/lib/types";

/**
 * A single quiet line, not a hero.
 *
 * Counts are context, not the answer to "what should I do next?" — so they get
 * one row under the actionable content rather than three large cards above it.
 * Each figure states exactly what was counted: lab leads and formal programmes
 * are different things and are never added together.
 */
export function StatStrip({ overview }: { overview: Overview }) {
  const c = overview.counts;
  const stats: { label: string; value: number; href: string }[] = [
    { label: "tracked", value: c.total, href: "/opportunities" },
    { label: "lab leads", value: c.lab_leads, href: "/research" },
    { label: "stated openings", value: c.verified_openings, href: "/research?state=opening" },
    { label: "research programmes", value: c.research_programs, href: "/opportunities?type=research_opening" },
    { label: "saved", value: c.saved, href: "/opportunities?status=saved" },
  ];

  return (
    <div className="scrollbar-thin flex min-w-0 items-center gap-x-5 gap-y-1 overflow-x-auto whitespace-nowrap border-y border-[var(--border-subtle)] py-2 text-xs">
      {stats.map((s) => (
        <Link
          key={s.label}
          href={s.href}
          className="group flex items-baseline gap-1.5 text-[var(--text-tertiary)] transition-colors hover:text-[var(--text-primary)]"
        >
          <span className="tnum font-medium text-[var(--text-primary)]">{s.value}</span>
          <span className="group-hover:underline">{s.label}</span>
        </Link>
      ))}
    </div>
  );
}
