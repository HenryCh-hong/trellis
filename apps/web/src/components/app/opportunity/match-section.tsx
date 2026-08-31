"use client";

/**
 * "Why you match" — the audit trail behind the fit score.
 *
 * The whole point of this section is that the number can be checked: every
 * component shows its own score, the weight applied to it, the points it
 * contributed, and the human reason. A component the scorer could not
 * evaluate says so instead of quietly contributing a zero.
 */

import * as React from "react";
import { RecommendationTag } from "@/components/app/indicators";
import { Button } from "@/components/ui/button";
import { PanelSection } from "@/components/ui/panel";
import { cn, formatDateTime } from "@/lib/utils";
import type { MatchDetail, ScoreComponent } from "@/lib/types";

/** A zero-weight component is excluded from the total — never a zero score. */
function isNotScored(c: ScoreComponent): boolean {
  return c.weight <= 0;
}

function formatWeight(weight: number): string {
  const s = weight.toFixed(2);
  return s.replace(/\.?0+$/, "") || "0";
}

export function MatchSection({
  match,
  onRematch,
  rematching,
}: {
  match: MatchDetail | null;
  onRematch: () => void;
  rematching: boolean;
}) {
  const action = (
    <Button size="xs" variant="ghost" onClick={onRematch} loading={rematching}>
      {rematching ? "Re-matching" : "Re-match"}
    </Button>
  );

  if (!match) {
    return (
      <PanelSection title="Why you match" action={action}>
        <p className="rounded-[var(--radius-md)] border border-dashed border-[var(--border)] px-3 py-3 text-xs leading-relaxed text-[var(--text-tertiary)]">
          This opportunity has not been scored against your profile yet, so there is no fit number
          to explain. Re-match to compare it against your resume, skills and coursework.
        </p>
      </PanelSection>
    );
  }

  const scored = match.breakdown.filter((c) => !isNotScored(c));
  // The API reports component `score` and `weighted` on a 0..1 scale, while
  // `fit_score` is already 0..100. Convert once here so the row renderer and the
  // drift check are comparing the same units.
  const weightedTotal = scored.reduce((sum, c) => sum + c.weighted, 0) * 100;
  const drift = Math.abs(weightedTotal - match.fit_score) > 1.5;

  return (
    <PanelSection title="Why you match" action={action}>
      <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <RecommendationTag value={match.recommendation} />
        <span className="text-2xs text-[var(--text-tertiary)]">
          Confidence {Math.round(match.confidence * 100)}%
        </span>
        <span className="text-2xs text-[var(--text-tertiary)]">Model {match.model}</span>
        {match.computed_at && (
          <span className="text-2xs text-[var(--text-tertiary)]">
            Scored {formatDateTime(match.computed_at)}
          </span>
        )}
      </div>

      {match.explanation && (
        <p className="mb-3 text-sm leading-relaxed text-[var(--text-primary)]">
          {match.explanation}
        </p>
      )}

      {match.breakdown.length > 0 ? (
        <div className="rounded-[var(--radius-md)] border border-[var(--border)]">
          <div className="flex items-center gap-3 border-b border-[var(--border-subtle)] bg-[var(--bg-subtle)] px-3 py-1.5">
            <span className="min-w-0 flex-1 text-2xs uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
              Component
            </span>
            <span className="w-20 shrink-0" />
            <span className="w-7 shrink-0 text-right text-2xs uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
              Sc
            </span>
            <span className="w-10 shrink-0 text-right text-2xs uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
              Wt
            </span>
            <span className="w-11 shrink-0 text-right text-2xs uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
              Pts
            </span>
          </div>

          <ul className="divide-y divide-[var(--border-subtle)]">
            {match.breakdown.map((c) => (
              <ComponentRow key={c.key} component={c} />
            ))}
          </ul>

          <div className="flex items-center gap-3 border-t border-[var(--border)] bg-[var(--bg-subtle)] px-3 py-2">
            <span className="min-w-0 flex-1 text-xs font-medium text-[var(--text-primary)]">
              Weighted total
            </span>
            <span className="w-20 shrink-0" />
            <span className="w-7 shrink-0" />
            <span className="w-10 shrink-0" />
            <span className="w-11 shrink-0 text-right text-xs font-semibold tnum text-[var(--text-primary)]">
              {weightedTotal.toFixed(1)}
            </span>
          </div>
          {drift && (
            <p className="border-t border-[var(--border-subtle)] px-3 py-1.5 text-2xs text-[var(--text-tertiary)]">
              The components add up to {weightedTotal.toFixed(1)} but the stored fit score is{" "}
              {Math.round(match.fit_score)} — the score was normalised after the breakdown was
              written.
            </p>
          )}
        </div>
      ) : (
        <p className="text-xs text-[var(--text-tertiary)]">
          The scorer returned a number without a component breakdown, so this score cannot be
          audited. Re-match to regenerate it.
        </p>
      )}

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <PointList
          title="Strengths"
          items={match.strengths}
          empty="No specific strengths were identified for this one."
          dot="bg-[var(--color-success-500)]"
        />
        <PointList
          title="Potential gaps"
          items={match.gaps}
          empty="No gaps were flagged against your profile."
          dot="bg-[var(--color-warn-500)]"
        />
      </div>

      {match.why_interesting && (
        <blockquote className="mt-4 border-l-2 border-[var(--accent-border)] pl-3 text-xs italic leading-relaxed text-[var(--text-secondary)]">
          {match.why_interesting}
        </blockquote>
      )}
    </PanelSection>
  );
}

function ComponentRow({ component: c }: { component: ScoreComponent }) {
  const notScored = isNotScored(c);
  const pct = Math.max(0, Math.min(100, c.score * 100));

  return (
    <li className="px-3 py-2">
      <div className="flex items-center gap-3">
        <span className="min-w-0 flex-1 truncate text-xs font-medium text-[var(--text-primary)]">
          {c.label}
        </span>

        {notScored ? (
          <span className="w-20 shrink-0 text-right text-2xs text-[var(--text-tertiary)]">
            Not scored
          </span>
        ) : (
          <span className="h-1 w-20 shrink-0 overflow-hidden rounded-full bg-[var(--bg-sunken)]">
            <span
              className="block h-full rounded-full bg-[var(--accent)]"
              style={{ width: `${pct}%` }}
            />
          </span>
        )}

        <span
          className={cn(
            "w-7 shrink-0 text-right text-xs tnum",
            notScored ? "text-[var(--text-disabled)]" : "text-[var(--text-primary)]",
          )}
        >
          {notScored ? "—" : Math.round(pct)}
        </span>
        <span className="w-10 shrink-0 text-right text-2xs tnum text-[var(--text-tertiary)]">
          {notScored ? "excl." : `×${formatWeight(c.weight)}`}
        </span>
        <span
          className={cn(
            "w-11 shrink-0 text-right text-xs tnum",
            notScored ? "text-[var(--text-disabled)]" : "text-[var(--text-secondary)]",
          )}
        >
          {notScored ? "0.0" : (c.weighted * 100).toFixed(1)}
        </span>
      </div>

      {c.reason && (
        <p className="mt-1 text-2xs leading-relaxed text-[var(--text-secondary)]">{c.reason}</p>
      )}
      {c.detail && c.detail.length > 0 && (
        <ul className="mt-1 flex flex-col gap-0.5">
          {c.detail.map((d, i) => (
            <li key={i} className="flex gap-1.5 text-2xs leading-relaxed text-[var(--text-tertiary)]">
              <span aria-hidden>·</span>
              <span>{d}</span>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function PointList({
  title,
  items,
  empty,
  dot,
}: {
  title: string;
  items: string[];
  empty: string;
  dot: string;
}) {
  return (
    <div>
      <h4 className="mb-1.5 text-2xs font-semibold uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
        {title}
      </h4>
      {items.length === 0 ? (
        <p className="text-2xs leading-relaxed text-[var(--text-tertiary)]">{empty}</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {items.map((item, i) => (
            <li key={i} className="flex gap-2 text-xs leading-relaxed text-[var(--text-primary)]">
              <span className={cn("mt-1.5 size-1.5 shrink-0 rounded-full", dot)} aria-hidden />
              <span className="min-w-0">{item}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
