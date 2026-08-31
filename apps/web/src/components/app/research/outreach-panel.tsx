"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { PanelSection, SidePanel } from "@/components/ui/panel";
import { Alert, ExternalLink, Skeleton } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import type { OutreachDraft, ResearchContext } from "@/lib/types";
import type { BackgroundPoint } from "./format";

/**
 * Outreach help: a first draft, and everything it was built from.
 *
 * Trellis does not send email. What it does is compose a draft out of facts it
 * can already point at — a dated paper from this lab, and lines from the
 * student's own profile and resumes — and then show those facts underneath, so
 * the student can check every claim before deciding to keep a word of it.
 *
 * The draft is deliberately unfinished. It never says the student read or
 * admired anything, because we do not know that, and the "before you send"
 * list says so out loud. When there is nothing recent that connects, or
 * nothing real on file about the student, the panel shows the reason instead
 * of an email: a generic cold email to a named professor is worse than none.
 */
export function OutreachPanel({
  context,
  background,
}: {
  context: ResearchContext;
  background: BackgroundPoint[];
}) {
  const toast = useToast();
  const [open, setOpen] = React.useState(false);
  const [draft, setDraft] = React.useState<OutreachDraft | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const facultyId = context.faculty.id;

  React.useEffect(() => {
    if (!open) return;
    let cancelled = false;
    api.research
      .outreach(facultyId)
      .then((d) => !cancelled && setDraft(d))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : "Could not build a draft."));
    return () => {
      cancelled = true;
    };
  }, [open, facultyId]);

  const full = draft?.body
    ? `Subject: ${draft.subject ?? ""}\n\n${draft.body}`
    : "";

  return (
    <>
      <Button variant="secondary" size="sm" onClick={() => setOpen(true)}>
        Prepare an outreach email
      </Button>

      <SidePanel
        open={open}
        onClose={() => setOpen(false)}
        width="narrow"
        title={<h2 className="text-sm font-semibold">Outreach to {context.faculty.name}</h2>}
        subtitle={
          <p className="mt-0.5 text-xs text-[var(--text-tertiary)]">
            A first draft — you edit it, you send it
          </p>
        }
        footer={
          draft?.body ? (
            <div className="space-y-2">
              <Button
                variant="primary"
                className="w-full"
                onClick={async () => {
                  await navigator.clipboard.writeText(full);
                  toast.push("Draft copied. Nothing has been sent.", "success");
                }}
              >
                Copy draft
              </Button>
              <p className="text-2xs leading-relaxed text-[var(--text-tertiary)]">
                Trellis does not send email. Copy this into your own mail client, edit it, and send
                it yourself.
              </p>
            </div>
          ) : null
        }
      >
        {error && (
          <PanelSection>
            <Alert tone="danger" title="Could not build a draft">
              {error}
            </Alert>
          </PanelSection>
        )}

        {!draft && !error && (
          <PanelSection>
            <Skeleton className="h-32 w-full" />
          </PanelSection>
        )}

        {draft?.refusal && (
          <PanelSection>
            <Alert tone="warn" title="No draft for this one">
              {draft.refusal}
            </Alert>
          </PanelSection>
        )}

        {draft?.body && (
          <>
            <PanelSection title={`Draft · ${draft.word_count} words`}>
              {draft.subject && (
                <p className="mb-2 text-xs">
                  <span className="text-[var(--text-tertiary)]">Subject: </span>
                  {draft.subject}
                </p>
              )}
              <pre className="whitespace-pre-wrap rounded-[var(--radius-sm)] bg-[var(--bg-sunken)] p-3 font-sans text-xs leading-relaxed text-[var(--text-primary)]">
                {draft.body}
              </pre>
            </PanelSection>

            <PanelSection title="Before you send">
              <ul className="space-y-1.5">
                {draft.todos.map((todo, i) => (
                  <li key={i} className="text-xs leading-relaxed text-[var(--color-warn-700)]">
                    · {todo}
                  </li>
                ))}
              </ul>
            </PanelSection>

            <PanelSection title="Research evidence used">
              <ul className="space-y-2">
                {draft.research_citations.map((c, i) => (
                  <li key={i} className="text-xs leading-relaxed">
                    <div className="text-[var(--text-primary)]">{c.label}</div>
                    {c.detail && (
                      <div className="text-[var(--text-tertiary)]">{c.detail}</div>
                    )}
                    {c.source_url && (
                      <ExternalLink href={c.source_url} className="text-2xs">
                        source
                      </ExternalLink>
                    )}
                  </li>
                ))}
              </ul>
            </PanelSection>

            <PanelSection title="Your evidence used">
              <p className="mb-2 text-2xs text-[var(--text-tertiary)]">
                Read from your profile and the resumes you uploaded. Nothing is invented.
              </p>
              <ul className="space-y-1.5">
                {draft.student_citations.map((c, i) => (
                  <li key={i} className="text-xs leading-relaxed">
                    <span className="text-[var(--text-primary)]">{c.label}</span>
                    {c.detail && c.detail !== c.label && (
                      <span className="text-[var(--text-tertiary)]"> — {c.detail}</span>
                    )}
                  </li>
                ))}
              </ul>
            </PanelSection>
          </>
        )}

        {background.length === 0 && !draft?.body && (
          <PanelSection title="Why there is nothing to draft from">
            <p className="text-xs leading-relaxed text-[var(--text-tertiary)]">
              Your profile does not yet record anything that overlaps this lab. Add your coursework
              and skills, or upload a resume, and this will fill in from your own material.
            </p>
          </PanelSection>
        )}

        {context.faculty.email && (
          <PanelSection title="Address">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs">{context.faculty.email}</span>
              {context.faculty.email_source_url && (
                <ExternalLink href={context.faculty.email_source_url} className="text-2xs">
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
