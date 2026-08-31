"use client";

/**
 * Provenance.
 *
 * Every extracted field is listed with the certainty it was recorded at and a
 * link back to the page it came from, so any single value on this screen can
 * be traced to a sentence someone can go and read.
 */

import * as React from "react";
import { CertaintyMark } from "@/components/app/indicators";
import { PanelSection } from "@/components/ui/panel";
import { Badge, ExternalLink, Tooltip } from "@/components/ui/primitives";
import { formatDateTime, hostOf } from "@/lib/utils";
import type { EvidencedField, OpportunityDetail } from "@/lib/types";

const METHOD_LABEL: Record<EvidencedField["method"], string> = {
  source: "stated on the page",
  regex: "pattern match",
  heuristic: "rule",
  llm: "language model",
  user: "entered by you",
};

function humanize(key: string): string {
  const spaced = key.replace(/_/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Unknown";
  if (Array.isArray(value)) {
    return value.length ? value.map((v) => String(v)).join(", ") : "Unknown";
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function SourceSection({ detail }: { detail: OpportunityDetail }) {
  const fields = Object.entries(detail.fields);

  return (
    <PanelSection title="Source">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        {detail.source_url ? (
          <ExternalLink href={detail.source_url} className="text-sm">
            {hostOf(detail.source_url)}
          </ExternalLink>
        ) : (
          <span className="text-sm text-[var(--text-tertiary)]">No source link recorded</span>
        )}
        {detail.source && <Badge tone="neutral">{detail.source.name}</Badge>}
        {detail.source?.is_mocked && (
          <Tooltip content="This source is a local fixture, not a live fetch. Treat the values as sample data.">
            <Badge tone="warn">Mock source</Badge>
          </Tooltip>
        )}
        {detail.source?.requires_auth && (
          <Tooltip content="The live source needs a login, so only what is publicly visible was read.">
            <Badge tone="neutral">Login-walled</Badge>
          </Tooltip>
        )}
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-3">
        <div>
          <dt className="text-2xs uppercase tracking-[0.04em] text-[var(--text-tertiary)]">
            First seen
          </dt>
          <dd className="mt-0.5 text-sm tnum text-[var(--text-primary)]">
            {formatDateTime(detail.first_seen_at)}
          </dd>
        </div>
        <div>
          <dt className="text-2xs uppercase tracking-[0.04em] text-[var(--text-tertiary)]">
            Last checked
          </dt>
          <dd className="mt-0.5 text-sm tnum text-[var(--text-primary)]">
            {formatDateTime(detail.last_checked_at)}
          </dd>
        </div>
      </dl>

      <div className="mt-4">
        <div className="mb-2 flex items-center gap-2">
          <h4 className="text-2xs font-semibold uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
            Extracted fields
          </h4>
          <span className="text-2xs tnum text-[var(--text-tertiary)]">
            {Math.round(detail.extraction_confidence * 100)}% overall confidence
          </span>
        </div>

        {fields.length === 0 ? (
          <p className="text-2xs leading-relaxed text-[var(--text-tertiary)]">
            No field-level provenance was recorded for this opportunity.
          </p>
        ) : (
          <ul className="divide-y divide-[var(--border-subtle)] rounded-[var(--radius-md)] border border-[var(--border)]">
            {fields.map(([key, field]) => (
              <li key={key} className="flex items-start gap-3 px-3 py-2">
                <span className="w-28 shrink-0 pt-px text-2xs text-[var(--text-tertiary)]">
                  {humanize(key)}
                </span>
                <div className="min-w-0 flex-1">
                  <Tooltip
                    content={
                      field.source_text
                        ? `“${field.source_text}”`
                        : `No sentence was captured — recorded by ${METHOD_LABEL[field.method]}.`
                    }
                  >
                    <span
                      className={
                        field.value === null || field.value === undefined
                          ? "text-xs text-[var(--text-tertiary)]"
                          : "text-xs text-[var(--text-primary)]"
                      }
                    >
                      {renderValue(field.value)}
                    </span>
                  </Tooltip>
                  <div className="mt-0.5 flex flex-wrap items-center gap-2">
                    <CertaintyMark certainty={field.certainty} />
                    <span className="text-2xs text-[var(--text-tertiary)]">
                      {METHOD_LABEL[field.method]} · {Math.round(field.confidence * 100)}%
                    </span>
                    {field.source_url && (
                      <ExternalLink href={field.source_url} className="text-2xs">
                        source
                      </ExternalLink>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </PanelSection>
  );
}
