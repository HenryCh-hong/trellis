"use client";

/**
 * About the role — the plain facts, with "Unknown" wherever the source page
 * was silent. Nothing in here is filled in from a guess.
 */

import * as React from "react";
import { EligibilityTag } from "@/components/app/indicators";
import { Button } from "@/components/ui/button";
import { KeyValue, PanelSection } from "@/components/ui/panel";
import { Badge, ExternalLink } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";
import type { OpportunityDetail } from "@/lib/types";

function Unknown({ children }: { children?: React.ReactNode }) {
  return (
    <span className="text-[var(--text-tertiary)]">{children ?? "Unknown"}</span>
  );
}

export function AboutSection({ detail }: { detail: OpportunityDetail }) {
  const [expanded, setExpanded] = React.useState(false);
  const description = detail.description?.trim() ?? "";
  const isLong = description.length > 520;

  const hoursValue =
    detail.hours_per_week !== null ? `${detail.hours_per_week} hrs/week` : null;
  const hasHours = hoursValue !== null || Boolean(detail.hours_note);

  return (
    <PanelSection title="About the role">
      {description ? (
        <div className="mb-4">
          <p
            className={cn(
              "whitespace-pre-line text-sm leading-relaxed text-[var(--text-primary)]",
              isLong && !expanded && "line-clamp-6",
            )}
          >
            {description}
          </p>
          {isLong && (
            <Button
              variant="link"
              size="xs"
              className="mt-1"
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded ? "Show less" : "Show full description"}
            </Button>
          )}
        </div>
      ) : (
        <p className="mb-4 text-xs leading-relaxed text-[var(--text-tertiary)]">
          No description was captured from the source page. Open the link in the Source section to
          read it directly.
        </p>
      )}

      <KeyValue
        columns={2}
        items={[
          {
            label: "Pay",
            value: detail.pay_text ? (
              <span className="tnum">{detail.pay_text}</span>
            ) : (
              <Unknown>Not stated</Unknown>
            ),
          },
          {
            label: "Hours",
            value: hasHours ? (
              <span>
                {hoursValue && <span className="tnum">{hoursValue}</span>}
                {hoursValue && detail.hours_note ? " · " : ""}
                {detail.hours_note}
              </span>
            ) : (
              <Unknown>Not stated</Unknown>
            ),
          },
          {
            label: "Location",
            value: detail.location ?? <Unknown>Not stated</Unknown>,
          },
          {
            label: "Department",
            value: detail.department ?? <Unknown />,
          },
          {
            label: "How to apply",
            value: detail.application_url ? (
              <ExternalLink href={detail.application_url} className="text-sm">
                {detail.application_method || "Application page"}
              </ExternalLink>
            ) : (
              detail.application_method ?? <Unknown>Not stated</Unknown>
            ),
          },
          {
            label: "Contact",
            value: detail.contact_email ? (
              <a
                href={`mailto:${detail.contact_email}`}
                className="text-[var(--accent)] underline-offset-2 hover:underline"
              >
                {detail.contact_name ?? detail.contact_email}
              </a>
            ) : (
              detail.contact_name ?? <Unknown>None listed</Unknown>
            ),
          },
        ]}
      />

      <div className="mt-4">
        <div className="mb-1.5 flex items-center gap-2">
          <h4 className="text-2xs font-semibold uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
            Eligibility
          </h4>
          <EligibilityTag state={detail.eligibility} reasons={detail.eligibility_reasons} />
        </div>
        {detail.eligibility_reasons.length === 0 ? (
          <p className="text-2xs leading-relaxed text-[var(--text-tertiary)]">
            No eligibility rules were found on the page, so this is not a judgement about whether
            you qualify.
          </p>
        ) : (
          <ul className="flex flex-col gap-1">
            {detail.eligibility_reasons.map((reason, i) => (
              <li
                key={i}
                className="flex gap-1.5 text-xs leading-relaxed text-[var(--text-secondary)]"
              >
                <span className="mt-1.5 size-1 shrink-0 rounded-full bg-[var(--color-neutral-400)]" aria-hidden />
                <span className="min-w-0">{reason}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {detail.skills.length > 0 && (
        <div className="mt-4">
          <h4 className="mb-1.5 text-2xs font-semibold uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
            Skills named in the posting
          </h4>
          <ul className="flex flex-wrap gap-1.5">
            {detail.skills.map((s) => (
              <li key={s}>
                <Badge tone="neutral">{s}</Badge>
              </li>
            ))}
          </ul>
        </div>
      )}
    </PanelSection>
  );
}
