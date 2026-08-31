"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { DeadlineCell, StatusPill, statusLabel } from "@/components/app/indicators";
import { PageHeader } from "@/components/app/page-header";
import { ReviewPanel } from "@/components/app/application/review-panel";
import {
  ReadinessList,
  ReadinessSummary,
} from "@/components/app/application/readiness-list";
import { Button } from "@/components/ui/button";
import { Checkbox, Select, Textarea } from "@/components/ui/input";
import {
  Alert,
  Badge,
  Card,
  ExternalLink,
  SectionHeader,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import type {
  ApplicationAnswerItem,
  ApplicationKit,
  OpportunityStatus,
  ReadinessItem,
  ResumeItem,
} from "@/lib/types";
import { cn, formatDateTime, hostOf } from "@/lib/utils";

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

/** Where "Continue preparation" sends you for each readiness row. Deadline and
 *  application link are facts, not tasks, so they have no destination. */
const ANCHORS: Record<string, string> = {
  resume: "kit-resume",
  questions: "kit-questions",
  sensitive: "kit-sensitive",
};

function jumpable(item: ReadinessItem): boolean {
  return item.key in ANCHORS || item.key.startsWith("document:");
}

export function KitClient({
  initial,
  resumes,
}: {
  initial: ApplicationKit;
  resumes: ResumeItem[];
}) {
  const router = useRouter();
  const toast = useToast();
  const [kit, setKit] = React.useState(initial);
  const [reviewOpen, setReviewOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);

  const opp = kit.opportunity;

  // Grouped by the stored category, so the screen shows exactly what Trellis
  // was allowed to do with each question. The one display rule on top: a
  // profile field the profile cannot actually answer belongs with the
  // questions you have to fill in, not under "From your profile".
  const fromProfile = kit.answers.filter(
    (a) => a.category === "safe_profile_field" && Boolean(a.answer),
  );
  const needsInput = kit.answers.filter(
    (a) =>
      a.category === "safe_generative" ||
      a.category === "unknown" ||
      (a.category === "safe_profile_field" && !a.answer),
  );
  const sensitive = kit.answers.filter((a) => a.category === "sensitive");

  function jumpTo(item: ReadinessItem) {
    const id = ANCHORS[item.key] ?? (item.key.startsWith("document:") ? "kit-documents" : null);
    if (!id) return;
    const node = document.getElementById(id);
    node?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function onPrimary() {
    if (kit.readiness.ready) {
      setReviewOpen(true);
      return;
    }
    const next = kit.readiness.items.find((i) => i.state !== "ready" && jumpable(i));
    if (next) jumpTo(next);
  }

  async function patch(body: Record<string, unknown>, message?: string) {
    setBusy(true);
    try {
      const updated = await api.applications.update(kit.id, body);
      setKit(updated);
      if (message) toast.push(message, "success");
      router.refresh();
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "That did not save", "error");
    } finally {
      setBusy(false);
    }
  }

  async function saveAnswer(answer: ApplicationAnswerItem, body: Record<string, unknown>) {
    try {
      const updated = await api.applications.answer(kit.id, answer.id, body);
      setKit(updated);
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "That did not save", "error");
    }
  }

  return (
    <>
      <PageHeader
        title={opp.title}
        description={[opp.organization, opp.department].filter(Boolean).join(" · ")}
        actions={<StatusPill status={kit.status as OpportunityStatus} />}
      />

      <div className="p-5">
        <Link
          href="/applications"
          className="text-xs text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
        >
          ← All applications
        </Link>

        <div className="mt-4 grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <div className="min-w-0 space-y-5">
            <Card className="p-4">
              <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs">
                <span className="text-[var(--text-tertiary)]">
                  Deadline:{" "}
                  <DeadlineCell
                    deadline={opp.deadline}
                    type={opp.deadline_type}
                    state={opp.deadline_state}
                    urgency={opp.urgency}
                    days={opp.days_until_deadline}
                  />
                </span>
                {kit.application_method && (
                  <span className="text-[var(--text-tertiary)]">
                    Method: <span className="text-[var(--text-primary)]">{kit.application_method}</span>
                  </span>
                )}
                {kit.application_url && (
                  <ExternalLink href={kit.application_url}>
                    {hostOf(kit.application_url)}
                  </ExternalLink>
                )}
              </div>
            </Card>

            {/* Resume */}
            <section id="kit-resume" className="scroll-mt-20">
              <SectionHeader
                title="Recommended resume"
                description="Trellis picks from what you uploaded. It never rewrites a resume."
              />
              <Card className="p-4">
                <div className="flex flex-wrap items-center gap-3">
                  <Select
                    aria-label="Resume to use"
                    value={kit.resume_id ?? ""}
                    disabled={busy}
                    onChange={(e) =>
                      patch({ resume_id: e.target.value }, "Resume choice saved")
                    }
                    className="w-[240px]"
                  >
                    <option value="">Choose a resume…</option>
                    {resumes.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.label}
                      </option>
                    ))}
                  </Select>
                  {kit.resume_locked_by_user && <Badge tone="neutral">Your choice</Badge>}
                </div>

                {kit.resume_recommendations.map((rec) => (
                  <div
                    key={rec.resume_id}
                    className={cn(
                      "mt-3 rounded-[var(--radius-md)] border p-3",
                      rec.resume_id === kit.resume_id
                        ? "border-[var(--accent-border)] bg-[var(--accent-soft)]"
                        : "border-[var(--border-subtle)]",
                    )}
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-xs font-medium">{rec.resume_label}</span>
                      <span className="text-2xs tabular-nums text-[var(--text-tertiary)]">
                        {Math.round(rec.score)}
                      </span>
                    </div>
                    {rec.rationale && (
                      <p className="mt-1 text-xs leading-relaxed text-[var(--text-secondary)]">
                        {rec.rationale}
                      </p>
                    )}
                    {rec.matched_strengths.length > 0 && (
                      <ul className="mt-2 space-y-0.5">
                        {rec.matched_strengths.slice(0, 3).map((s) => (
                          <li key={s} className="text-2xs text-[var(--color-success-700)]">
                            + {s}
                          </li>
                        ))}
                      </ul>
                    )}
                    {rec.weak_or_missing.length > 0 && (
                      <ul className="mt-1 space-y-0.5">
                        {rec.weak_or_missing.slice(0, 2).map((s) => (
                          <li key={s} className="text-2xs text-[var(--text-tertiary)]">
                            − {s}
                          </li>
                        ))}
                      </ul>
                    )}
                    {rec.emphasize.length > 0 && (
                      <div className="mt-2 border-l-2 border-[var(--border)] pl-2.5">
                        <div className="text-2xs uppercase tracking-[0.04em] text-[var(--text-tertiary)]">
                          Worth leading with
                        </div>
                        {rec.emphasize.slice(0, 3).map((e, i) => (
                          <p key={i} className="mt-1 text-2xs italic text-[var(--text-secondary)]">
                            “{e.text}”
                          </p>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </Card>
            </section>

            {/* Documents */}
            <section id="kit-documents" className="scroll-mt-20">
              <SectionHeader title="Required documents" count={kit.documents.length} />
              <div className="space-y-2">
                {kit.documents.map((doc) => (
                  <Card
                    key={doc.id}
                    className={cn(
                      "flex items-start justify-between gap-3 p-3",
                      doc.status === "missing" &&
                        doc.required &&
                        "border-[var(--color-danger-200)] bg-[var(--color-danger-50)]",
                    )}
                  >
                    <div className="min-w-0">
                      <div className="text-xs font-medium">{doc.label}</div>
                      {doc.note && (
                        <p className="mt-0.5 text-2xs text-[var(--text-secondary)]">{doc.note}</p>
                      )}
                    </div>
                    <Badge
                      tone={
                        doc.status === "ready"
                          ? "success"
                          : doc.status === "needs_user"
                            ? "warn"
                            : "danger"
                      }
                    >
                      {doc.status === "ready"
                        ? "Ready"
                        : doc.status === "needs_user"
                          ? "Needs you"
                          : "Missing"}
                    </Badge>
                  </Card>
                ))}
              </div>
            </section>

            {/* Questions */}
            <section id="kit-questions" className="scroll-mt-20">
              <SectionHeader title="Questions" count={kit.answers.length} />

              {fromProfile.length > 0 && (
                <div className="mb-4">
                  <h4 className="mb-1.5 text-2xs uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
                    From your profile
                  </h4>
                  <Card className="divide-y divide-[var(--border-subtle)]">
                    {fromProfile.map((a) => (
                      <div key={a.id} className="flex items-baseline gap-3 px-3 py-2">
                        <span className="w-[46%] shrink-0 text-xs text-[var(--text-secondary)]">
                          {a.question}
                        </span>
                        <span className="min-w-0 flex-1 truncate text-xs">{a.answer}</span>
                      </div>
                    ))}
                  </Card>
                </div>
              )}

              {needsInput.length > 0 && (
                <div className="mb-4">
                  <h4 className="mb-1.5 text-2xs uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
                    Needs your input
                  </h4>
                  <div className="space-y-3">
                    {needsInput.map((a) => (
                      <div key={a.id}>
                        <label className="mb-1 block text-xs text-[var(--text-secondary)]">
                          {a.question}
                          {a.source === "llm_draft" && (
                            <Badge tone="warn" className="ml-2">
                              Draft — check it
                            </Badge>
                          )}
                          {/* Quiet, not alarming: an unrecognised question is
                              simply one Trellis did not touch. */}
                          {a.category === "unknown" && (
                            <span className="ml-2 text-2xs text-[var(--text-tertiary)]">
                              Trellis did not recognise this one
                            </span>
                          )}
                          {a.category === "safe_profile_field" && (
                            <span className="ml-2 text-2xs text-[var(--text-tertiary)]">
                              Not in your profile yet
                            </span>
                          )}
                        </label>
                        <Textarea
                          defaultValue={a.answer ?? ""}
                          placeholder="Your answer"
                          onBlur={(e) => {
                            if (e.target.value !== (a.answer ?? "")) {
                              saveAnswer(a, { answer: e.target.value });
                            }
                          }}
                        />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {sensitive.length > 0 && (
                <div id="kit-sensitive" className="scroll-mt-20">
                  <h4 className="mb-1.5 text-2xs uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
                    Only you can answer these
                  </h4>
                  <Alert tone="neutral" className="mb-2">
                    Trellis never answers work-authorisation, visa, demographic, disability,
                    veteran-status, criminal-history or legal-attestation questions for you, and
                    never reuses an answer unless you say so.
                  </Alert>
                  <div className="space-y-3">
                    {sensitive.map((a) => (
                      <div key={a.id}>
                        <label className="mb-1 block text-xs text-[var(--text-secondary)]">
                          {a.question}
                        </label>
                        <Textarea
                          defaultValue={a.answer ?? ""}
                          placeholder="You answer this one"
                          onBlur={(e) => {
                            if (e.target.value !== (a.answer ?? "")) {
                              saveAnswer(a, { answer: e.target.value });
                            }
                          }}
                        />
                        <div className="mt-1.5">
                          <Checkbox
                            aria-label={`Remember my answer to: ${a.question}`}
                            checked={a.reuse_approved}
                            onChange={(e) =>
                              saveAnswer(a, { reuse_approved: e.target.checked })
                            }
                            label={
                              <span className="text-2xs text-[var(--text-tertiary)]">
                                Remember this answer for future applications
                              </span>
                            }
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </section>

            {kit.events.length > 0 && (
              <section className="pb-8">
                <SectionHeader title="Timeline" />
                <ol className="space-y-1.5">
                  {kit.events.map((e) => (
                    <li key={e.id} className="flex gap-3 text-2xs">
                      <span className="w-[130px] shrink-0 text-[var(--text-tertiary)]">
                        {formatDateTime(e.created_at)}
                      </span>
                      <span className="text-[var(--text-secondary)]">
                        {e.kind === "status" && e.to_status
                          ? `Moved to ${statusLabel(e.to_status as OpportunityStatus)}`
                          : e.note || e.kind}
                      </span>
                    </li>
                  ))}
                </ol>
              </section>
            )}
          </div>

          {/* Sticky summary */}
          <aside className="lg:sticky lg:top-16 lg:self-start">
            <Card className="p-4">
              <div className="mb-3">
                <div className="mb-1.5 text-2xs uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
                  Status
                </div>
                <Select
                  aria-label="Application status"
                  value=""
                  disabled={busy || !MOVE_TARGETS[kit.status]?.length}
                  onChange={(e) =>
                    e.target.value &&
                    patch({ status: e.target.value }, `Moved to ${statusLabel(e.target.value as OpportunityStatus)}`)
                  }
                >
                  <option value="">{statusLabel(kit.status as OpportunityStatus)}</option>
                  {(MOVE_TARGETS[kit.status] ?? []).map((s) => (
                    <option key={s} value={s}>
                      Move to {statusLabel(s)}
                    </option>
                  ))}
                </Select>
              </div>

              <div className="mb-3">
                <div className="mb-1.5 text-2xs uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
                  Application readiness
                </div>
                {/* The same server-computed list the opportunity panel shows.
                    Rows that still need work jump to the section that fixes them. */}
                <ReadinessList readiness={kit.readiness} onJump={jumpTo} canJump={jumpable} />
                <div className="mt-2.5 border-t border-[var(--border-subtle)] pt-2.5">
                  <ReadinessSummary readiness={kit.readiness} />
                </div>
              </div>

              <Button variant="primary" className="w-full" onClick={onPrimary}>
                {kit.readiness.cta}
              </Button>
              {!kit.readiness.ready && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="mt-1.5 w-full"
                  onClick={() => setReviewOpen(true)}
                >
                  See what would be submitted
                </Button>
              )}
              <p className="mt-2 text-2xs leading-relaxed text-[var(--text-tertiary)]">
                Trellis never submits an application. You review the exact payload, approve it, and
                submit on the site yourself.
              </p>

              {kit.approved_at && kit.readiness.ready ? (
                <Alert tone="success" className="mt-3">
                  Approved {formatDateTime(kit.approved_at)}. Editing anything above clears this.
                </Alert>
              ) : kit.approved_at ? (
                // The payload changed after approval — the server will refuse the
                // stale hash, so the banner must not keep claiming it is approved.
                <Alert tone="warn" className="mt-3">
                  Approved {formatDateTime(kit.approved_at)}, but this application has changed
                  since. Review it again before applying.
                </Alert>
              ) : null}

              <Button
                variant="secondary"
                className="mt-3 w-full"
                disabled={busy || kit.status === "submitted"}
                onClick={async () => {
                  setBusy(true);
                  try {
                    setKit(await api.applications.markSubmitted(kit.id));
                    toast.push("Marked as submitted", "success");
                    router.refresh();
                  } catch (error) {
                    toast.push(
                      error instanceof Error ? error.message : "Could not update",
                      "error",
                    );
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Mark as submitted
              </Button>
            </Card>
          </aside>
        </div>
      </div>

      {reviewOpen && (
        <ReviewPanel
          key={`review-${kit.id}`}
          open
          onClose={() => setReviewOpen(false)}
          applicationId={kit.id}
          applicationUrl={kit.application_url}
          onApproved={(updated) => setKit(updated)}
        />
      )}
    </>
  );
}
