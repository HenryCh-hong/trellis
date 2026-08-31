"use client";

/**
 * Application materials: what the posting asks for, and which résumé fits it.
 *
 * The "emphasize" lines are quoted verbatim from the résumé — they are things
 * the student already wrote, surfaced for reuse. Nothing here is generated
 * copy, so it is rendered as a quotation, not as a suggestion to paste.
 */

import * as React from "react";
import { Button } from "@/components/ui/button";
import { PanelSection } from "@/components/ui/panel";
import { Badge } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";
import type { ResumeRecommendationItem } from "@/lib/types";

export function MaterialsSection({
  documents,
  recommendations,
  recommendedResumeId,
}: {
  documents: string[];
  recommendations: ResumeRecommendationItem[];
  recommendedResumeId: string | null;
}) {
  const [showAll, setShowAll] = React.useState(false);

  const ranked = [...recommendations].sort((a, b) => a.rank - b.rank || b.score - a.score);
  const best = ranked[0] ?? null;
  const rest = ranked.slice(1);

  return (
    <PanelSection title="Application materials">
      <h4 className="mb-1.5 text-2xs font-semibold uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
        Documents requested
      </h4>
      {documents.length === 0 ? (
        <p className="text-xs leading-relaxed text-[var(--text-tertiary)]">
          The posting does not list the documents it wants. Check the source page before you send
          anything — assume at least a résumé.
        </p>
      ) : (
        <ul className="flex flex-wrap gap-1.5">
          {documents.map((d) => (
            <li key={d}>
              <Badge tone="neutral">{d}</Badge>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-4 flex items-center gap-2">
        <h4 className="text-2xs font-semibold uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
          Résumé to use
        </h4>
        {rest.length > 0 && (
          <Button
            size="xs"
            variant="ghost"
            className="ml-auto"
            onClick={() => setShowAll((v) => !v)}
          >
            {showAll ? "Hide other résumés" : `Compare ${rest.length} other`}
          </Button>
        )}
      </div>

      {!best ? (
        <p className="mt-1.5 text-xs leading-relaxed text-[var(--text-tertiary)]">
          No résumé has been scored against this opportunity. Upload one on the Résumés page and it
          will be compared automatically.
        </p>
      ) : (
        <div className="mt-2 flex flex-col gap-2">
          <ResumeCard
            item={best}
            best
            isSelected={recommendedResumeId === null || recommendedResumeId === best.resume_id}
          />
          {showAll &&
            rest.map((r) => (
              <ResumeCard key={r.resume_id} item={r} isSelected={recommendedResumeId === r.resume_id} />
            ))}
          {!showAll && rest.length > 0 && (
            <p className="text-2xs text-[var(--text-tertiary)]">
              {rest.map((r) => `${r.resume_label} ${Math.round(r.score)}`).join(" · ")}
            </p>
          )}
        </div>
      )}
    </PanelSection>
  );
}

function ResumeCard({
  item,
  best,
  isSelected,
}: {
  item: ResumeRecommendationItem;
  best?: boolean;
  isSelected: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-[var(--radius-md)] border px-3 py-2.5",
        best ? "border-[var(--accent-border)] bg-[var(--accent-soft)]" : "border-[var(--border)]",
      )}
    >
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-xs font-medium text-[var(--text-primary)]">
          {item.resume_label}
        </span>
        {best && <Badge tone="accent">Best fit</Badge>}
        {best && !isSelected && <Badge tone="warn">Scorer picked another</Badge>}
        <span className="shrink-0 text-xs font-semibold tnum text-[var(--text-primary)]">
          {Math.round(item.score)}
        </span>
      </div>

      {item.rationale && (
        <p className="mt-1.5 text-2xs leading-relaxed text-[var(--text-secondary)]">
          {item.rationale}
        </p>
      )}

      <div className="mt-2 grid gap-3 sm:grid-cols-2">
        <MiniList
          title="Matched strengths"
          items={item.matched_strengths}
          empty="Nothing in this résumé lined up directly."
          dot="bg-[var(--color-success-500)]"
        />
        <MiniList
          title="Weak or missing"
          items={item.weak_or_missing}
          empty="Nothing obviously missing."
          dot="bg-[var(--color-warn-500)]"
        />
      </div>

      {item.emphasize.length > 0 && (
        <div className="mt-3">
          <h5 className="mb-1.5 text-2xs font-semibold uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
            Lines to lead with
          </h5>
          <ul className="flex flex-col gap-2">
            {item.emphasize.map((e, i) => (
              <li key={i} className="border-l-2 border-[var(--border-strong)] pl-2.5">
                <p className="text-xs italic leading-relaxed text-[var(--text-primary)]">
                  &ldquo;{e.text}&rdquo;
                </p>
                <p className="mt-0.5 text-2xs leading-relaxed text-[var(--text-tertiary)]">
                  {e.why}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function MiniList({
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
      <h5 className="mb-1 text-2xs font-semibold uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
        {title}
      </h5>
      {items.length === 0 ? (
        <p className="text-2xs leading-relaxed text-[var(--text-tertiary)]">{empty}</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {items.map((s, i) => (
            <li key={i} className="flex gap-1.5 text-2xs leading-relaxed text-[var(--text-secondary)]">
              <span className={cn("mt-1 size-1 shrink-0 rounded-full", dot)} aria-hidden />
              <span className="min-w-0">{s}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
