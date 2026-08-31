"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/input";
import { PanelSection, SidePanel } from "@/components/ui/panel";
import { Alert, Badge, ExternalLink, Skeleton } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import type { ApplicationKit, SubmissionPlan } from "@/lib/types";
import { hostOf } from "@/lib/utils";

const SOURCE_LABEL: Record<string, string> = {
  profile: "from your profile",
  user: "you entered this",
  resume: "from your resume",
  llm_draft: "AI draft — check it",
};

/**
 * The consent step.
 *
 * Approval is bound to a hash of exactly this payload. If anything changes
 * afterwards the server refuses the stale approval, which is why the panel
 * always re-fetches rather than trusting a cached plan.
 */
export function ReviewPanel({
  open,
  onClose,
  applicationId,
  applicationUrl,
  onApproved,
}: {
  open: boolean;
  onClose: () => void;
  applicationId: string;
  applicationUrl: string | null;
  onApproved: (kit: ApplicationKit) => void;
}) {
  const toast = useToast();
  const [plan, setPlan] = React.useState<SubmissionPlan | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [confirmed, setConfirmed] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [handedOff, setHandedOff] = React.useState(false);

  const fetchPlan = React.useCallback(async () => {
    try {
      setPlan(await api.applications.plan(applicationId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not build the submission plan.");
    }
  }, [applicationId]);

  /** Re-fetch after a stale-hash rejection: here the resets are the point. */
  const reload = React.useCallback(async () => {
    setPlan(null);
    setConfirmed(false);
    await fetchPlan();
  }, [fetchPlan]);

  // The panel is mounted only while open (see the kit page), so it starts from
  // clean state and the effect only has to fetch.
  //
  // The lint rule cannot see past the await inside fetchPlan and reads its
  // setState as synchronous. It is not: the plan is fetched over the network
  // first, so there is no cascading render to avoid here.
  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void fetchPlan();
  }, [fetchPlan]);

  async function approve() {
    if (!plan) return;
    setBusy(true);
    try {
      const kit = await api.applications.approve(applicationId, plan.payload_hash);
      onApproved(kit);
      setHandedOff(true);
      toast.push("Approved. Nothing has been submitted yet.", "success");
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError(e.message);
        await reload();
      } else {
        toast.push(e instanceof Error ? e.message : "Could not approve", "error");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <SidePanel
      open={open}
      onClose={onClose}
      title={<h2 className="text-sm font-semibold">Review before you apply</h2>}
      subtitle={
        <p className="mt-0.5 text-xs text-[var(--text-tertiary)]">
          Exactly what would be submitted, and what would not
        </p>
      }
      footer={
        plan && !handedOff ? (
          <div className="space-y-2.5">
            <Checkbox
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
              label={
                <span className="text-xs">
                  I&apos;ve reviewed this and approve submitting it
                </span>
              }
            />
            <Button
              variant="primary"
              className="w-full"
              disabled={!confirmed || busy}
              loading={busy}
              onClick={approve}
            >
              Approve
            </Button>
          </div>
        ) : handedOff ? (
          <div className="space-y-2">
            <Button
              variant="primary"
              className="w-full"
              onClick={() => {
                if (plan?.target_url || applicationUrl) {
                  window.open(plan?.target_url ?? applicationUrl ?? "", "_blank", "noopener");
                }
              }}
            >
              Open the application page
            </Button>
            <p className="text-2xs leading-relaxed text-[var(--text-tertiary)]">
              Trellis has not submitted anything. Fill the form on the site, then mark this
              application as submitted.
            </p>
          </div>
        ) : null
      }
    >
      {error && (
        <PanelSection>
          <Alert tone="danger" title="This plan changed">
            {error}
          </Alert>
        </PanelSection>
      )}

      {!plan && !error && (
        <PanelSection>
          <div className="space-y-2">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        </PanelSection>
      )}

      {plan && (
        <>
          <PanelSection title="Where it goes">
            {plan.target_url ? (
              <ExternalLink href={plan.target_url} className="text-xs">
                {hostOf(plan.target_url)}
              </ExternalLink>
            ) : (
              <p className="text-xs text-[var(--text-tertiary)]">
                No application URL was found for this opportunity.
              </p>
            )}
            {plan.method && (
              <p className="mt-1 text-2xs text-[var(--text-tertiary)]">
                Method: {plan.method}
              </p>
            )}
          </PanelSection>

          <PanelSection title={`Will be submitted (${plan.fields.length})`}>
            <div className="divide-y divide-[var(--border-subtle)]">
              {plan.fields.map((f) => (
                <div key={f.key} className="py-2">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-xs text-[var(--text-secondary)]">{f.label}</span>
                    <span className="shrink-0 text-2xs text-[var(--text-tertiary)]">
                      {SOURCE_LABEL[f.source] ?? f.source}
                    </span>
                  </div>
                  <div className="mt-0.5 break-words text-xs">{f.value}</div>
                  {f.note && (
                    <div className="mt-0.5 text-2xs text-[var(--color-warn-700)]">{f.note}</div>
                  )}
                </div>
              ))}
            </div>
          </PanelSection>

          {plan.attachments.length > 0 && (
            <PanelSection title="Attachments">
              <ul className="space-y-1">
                {plan.attachments.map((a, i) => (
                  <li key={i} className="flex items-center gap-2 text-xs">
                    <Badge tone="neutral">{a.kind}</Badge>
                    <span className="truncate">{a.filename || a.label}</span>
                  </li>
                ))}
              </ul>
            </PanelSection>
          )}

          <PanelSection title={`Deliberately withheld (${plan.withheld.length})`}>
            {plan.withheld.length === 0 ? (
              <p className="text-xs text-[var(--text-tertiary)]">Nothing is being withheld.</p>
            ) : (
              <ul className="space-y-2.5">
                {plan.withheld.map((w, i) => (
                  <li key={i}>
                    <div className="text-xs text-[var(--text-primary)]">{w.label}</div>
                    <div className="mt-0.5 text-2xs leading-relaxed text-[var(--text-tertiary)]">
                      {w.reason}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </PanelSection>

          <PanelSection title="What happens next">
            <ol className="space-y-1.5">
              {plan.manual_steps.map((s, i) => (
                <li key={i} className="flex gap-2 text-xs leading-relaxed text-[var(--text-secondary)]">
                  <span className="tabular-nums text-[var(--text-tertiary)]">{i + 1}.</span>
                  {s}
                </li>
              ))}
            </ol>
            {plan.requires_user_at.length > 0 && (
              <Alert tone="warn" className="mt-3" title="You take over at">
                <ul className="mt-1 space-y-0.5">
                  {plan.requires_user_at.map((r, i) => (
                    <li key={i}>· {r}</li>
                  ))}
                </ul>
              </Alert>
            )}
          </PanelSection>
        </>
      )}
    </SidePanel>
  );
}
