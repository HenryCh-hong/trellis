"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { PanelSection, SidePanel } from "@/components/ui/panel";
import { Alert, ExternalLink } from "@/components/ui/primitives";
import type { ResearchContext } from "@/lib/types";
import type { BackgroundPoint } from "./format";

/**
 * Outreach help — deliberately not a ghostwriter.
 *
 * Trellis does not send email and does not hand over a ready-to-paste message.
 * A cold email that a student did not write is easy to spot, and a generated
 * one would inevitably claim things about them we cannot verify. So this shows
 * the *points to make*, each traced to something real: the lab's own recent
 * work, and the student's own profile.
 */
export function OutreachPanel({
  context,
  background,
}: {
  context: ResearchContext;
  background: BackgroundPoint[];
}) {
  const [open, setOpen] = React.useState(false);
  const recent = context.evidence.filter((e) => e.year !== null).slice(0, 3);

  return (
    <>
      <Button variant="secondary" size="sm" onClick={() => setOpen(true)}>
        Plan an outreach email
      </Button>

      <SidePanel
        open={open}
        onClose={() => setOpen(false)}
        width="narrow"
        title={
          <h2 className="text-sm font-semibold">
            Outreach to {context.faculty.name}
          </h2>
        }
        subtitle={
          <p className="mt-0.5 text-xs text-[var(--text-tertiary)]">
            Points to make — you write the email
          </p>
        }
      >
        <PanelSection>
          <Alert tone="neutral">
            Trellis does not send email and will not write one for you. A cold email works because
            it is specific and yours; a generated one is neither, and could claim something you
            have not done.
          </Alert>
        </PanelSection>

        <PanelSection title="Open with their actual work">
          {recent.length === 0 ? (
            <p className="text-xs text-[var(--text-tertiary)]">
              No dated recent work was found, so there is nothing specific to open with. That alone
              is a reason to be cautious about this lead.
            </p>
          ) : (
            <ul className="space-y-2.5">
              {recent.map((e) => (
                <li key={e.id} className="text-xs leading-relaxed">
                  <span className="text-[var(--text-tertiary)]">{e.year} · </span>
                  {e.url ? (
                    <ExternalLink href={e.url}>{e.title}</ExternalLink>
                  ) : (
                    <span className="text-[var(--text-primary)]">{e.title}</span>
                  )}
                  {e.summary && (
                    <p className="mt-0.5 text-[var(--text-tertiary)]">{e.summary}</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </PanelSection>

        <PanelSection title="Connect it to what you have done">
          {background.length === 0 ? (
            <p className="text-xs text-[var(--text-tertiary)]">
              Your profile does not yet record anything that overlaps this lab. Add your coursework
              and skills, or upload a resume, and this will fill in from your own material.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {background.map((b) => (
                <li key={b.label} className="text-xs leading-relaxed">
                  <span className="text-[var(--text-primary)]">{b.label}</span>
                  {b.detail && (
                    <span className="text-[var(--text-tertiary)]"> — {b.detail}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 text-2xs text-[var(--text-tertiary)]">
            Only things already on your profile appear here. Nothing is invented, and nothing is
            added on your behalf.
          </p>
        </PanelSection>

        <PanelSection title="Then ask for one small thing">
          <ul className="space-y-1.5 text-xs leading-relaxed text-[var(--text-secondary)]">
            <li>· Say which project you would want to work on, and why that one.</li>
            <li>· State how many hours a week you can commit and for how long.</li>
            <li>· Attach the resume Trellis recommended for this lead.</li>
            <li>· Ask for a short conversation, not a position.</li>
          </ul>
        </PanelSection>

        {context.faculty.email && (
          <PanelSection title="Address">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs">{context.faculty.email}</span>
              {context.faculty.email_source_url && (
                <ExternalLink
                  href={context.faculty.email_source_url}
                  className="text-2xs"
                >
                  source
                </ExternalLink>
              )}
            </div>
            {context.faculty.email_certainty !== "verified" && (
              <p className="mt-1.5 text-2xs text-[var(--color-warn-700)]">
                We could not confirm this address literally appears on the page it was read from.
                Check it before sending.
              </p>
            )}
          </PanelSection>
        )}
      </SidePanel>
    </>
  );
}
