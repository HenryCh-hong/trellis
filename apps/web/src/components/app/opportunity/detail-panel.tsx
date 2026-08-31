"use client";

/**
 * Opportunity detail panel.
 *
 * The shell renders immediately from the row that was clicked, so the panel
 * never flashes empty. `DetailBody` is keyed by opportunity id, so arrowing
 * through the list gives each row a clean fetch without replaying the panel's
 * slide-in. Mutations are applied to the list first and rolled back if the
 * request fails — the row and the panel can never disagree.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  EligibilityTag,
  ScoreMeter,
  StatusPill,
  TypeTag,
  statusLabel,
} from "@/components/app/indicators";
import { AboutSection } from "./about-section";
import { MaterialsSection } from "./materials-section";
import { MatchSection } from "./match-section";
import { RequirementsSection } from "./requirements-section";
import { ResearchSection } from "./research-section";
import { SourceSection } from "./source-section";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { PanelSection, SidePanel } from "@/components/ui/panel";
import { Alert, Badge, ExternalLink, Skeleton, Tooltip } from "@/components/ui/primitives";
import { ReminderDialog } from "@/components/app/reminder-dialog";
import { useToast } from "@/components/ui/toast";
import { api, ApiError } from "@/lib/api";
import { hostOf } from "@/lib/utils";
import type {
  OpportunityDetail,
  OpportunityListItem,
  OpportunityStatus,
} from "@/lib/types";

const STATUS_OPTIONS: OpportunityStatus[] = [
  "new",
  "saved",
  "preparing",
  "ready_to_apply",
  "applying",
  "submitted",
  "interview",
  "offer",
  "rejected",
  "archived",
];

function messageOf(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function joinDistinct(parts: (string | null)[]): string {
  return parts
    .filter((v): v is string => Boolean(v))
    .filter((v, i, all) => all.indexOf(v) === i)
    .join(" · ");
}

type Busy = "status" | "prepare" | null;

export function OpportunityPanel({
  item,
  onClose,
  onPatch,
}: {
  item: OpportunityListItem;
  onClose: () => void;
  onPatch: (id: string, patch: Partial<OpportunityListItem>) => void;
}) {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = React.useState<Busy>(null);
  const [reminderOpen, setReminderOpen] = React.useState(false);

  const changeStatus = React.useCallback(
    async (next: OpportunityStatus) => {
      if (next === item.status) return;
      const previous = item.status;
      onPatch(item.id, { status: next });
      setBusy("status");
      try {
        const updated = await api.opportunities.setStatus(item.id, next);
        onPatch(item.id, { status: updated.status });
        toast.push(`Moved to ${statusLabel(updated.status)}`);
      } catch (err) {
        onPatch(item.id, { status: previous });
        toast.push(messageOf(err, "Could not change the status."), "error");
      } finally {
        setBusy(null);
      }
    },
    [item.id, item.status, onPatch, toast],
  );

  const prepare = React.useCallback(async () => {
    if (item.has_application && item.application_id) {
      router.push(`/applications/${item.application_id}`);
      return;
    }
    const previous = {
      status: item.status,
      has_application: item.has_application,
      application_id: item.application_id,
    };
    onPatch(item.id, { status: "preparing", has_application: true });
    setBusy("prepare");
    try {
      const kit = await api.applications.create(item.id);
      onPatch(item.id, {
        status: kit.status,
        has_application: true,
        application_id: kit.id,
      });
      toast.push("Application kit created", "success");
      router.push(`/applications/${kit.id}`);
    } catch (err) {
      onPatch(item.id, previous);
      toast.push(messageOf(err, "Could not create the application kit."), "error");
    } finally {
      setBusy(null);
    }
  }, [item, onPatch, router, toast]);


  const org = joinDistinct([item.lab_name, item.organization, item.department]);
  const canSave = item.status === "new" || item.status === "saved";

  return (
    <SidePanel
      open
      onClose={onClose}
      width="wide"
      actions={
        item.source_url ? (
          <ExternalLink href={item.source_url} className="mr-1 text-2xs">
            {hostOf(item.source_url)}
          </ExternalLink>
        ) : undefined
      }
      title={
        <div className="min-w-0">
          <h2 className="text-md font-semibold leading-snug tracking-[-0.012em] text-[var(--text-primary)]">
            {item.title}
          </h2>
          {org && <p className="mt-0.5 truncate text-xs text-[var(--text-secondary)]">{org}</p>}
          {item.pi_name && (
            <p className="truncate text-xs text-[var(--text-tertiary)]">{item.pi_name}</p>
          )}
        </div>
      }
      subtitle={
        <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <TypeTag type={item.type} />
          <StatusPill status={item.status} />
          <EligibilityTag state={item.eligibility} />
          {item.is_new && <Badge tone="accent">New</Badge>}
          <span className="ml-auto">
            <ScoreMeter score={item.fit_score} confidence={item.fit_confidence} size="lg" />
          </span>
        </div>
      }
      footer={
        <div className="flex flex-wrap items-center gap-2">
          {canSave && (
            <Button
              variant="secondary"
              size="sm"
              loading={busy === "status"}
              onClick={() => void changeStatus(item.status === "saved" ? "new" : "saved")}
            >
              {item.status === "saved" ? "Saved" : "Save"}
            </Button>
          )}
          <Button
            variant="primary"
            size="sm"
            loading={busy === "prepare"}
            onClick={() => void prepare()}
          >
            {item.has_application ? "Open application" : "Prepare application"}
          </Button>
          <Tooltip
            content={
              item.deadline
                ? undefined
                : "No deadline was found on the source page, so there is no date to remind you about."
            }
          >
            <Button
              variant="ghost"
              size="sm"
              disabled={!item.deadline}
              onClick={() => setReminderOpen(true)}
            >
              {item.has_reminder ? "Reminder \u00b7 export" : "Add reminder"}
            </Button>
          </Tooltip>

          <div className="ml-auto w-[148px]">
            <Select
              aria-label="Pipeline status"
              className="h-7 w-full pl-2 pr-6 text-xs"
              value={item.status}
              disabled={busy === "status"}
              onChange={(e) => void changeStatus(e.target.value as OpportunityStatus)}
            >
              {STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {statusLabel(s)}
                </option>
              ))}
            </Select>
          </div>
        </div>
      }
    >
      <DetailBody key={item.id} id={item.id} onPatch={onPatch} />
      {reminderOpen && (
        <ReminderDialog
          key={`reminder-${item.id}`}
          open
          onClose={() => setReminderOpen(false)}
          opportunity={item}
          onCreated={() => onPatch(item.id, { has_reminder: true })}
        />
      )}
    </SidePanel>
  );
}

/* -------------------------------------------------------------------- body */

function DetailBody({
  id,
  onPatch,
}: {
  id: string;
  onPatch: (id: string, patch: Partial<OpportunityListItem>) => void;
}) {
  const toast = useToast();
  const [detail, setDetail] = React.useState<OpportunityDetail | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [attempt, setAttempt] = React.useState(0);
  const [rematching, setRematching] = React.useState(false);

  // Nothing yet and no failure yet means the request is still in flight —
  // derived rather than a third state variable that could disagree.
  const loading = detail === null && loadError === null;

  React.useEffect(() => {
    let cancelled = false;
    api.opportunities
      .get(id)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setLoadError(
          messageOf(err, "The detail request failed. The backend may not be running."),
        );
      });
    return () => {
      cancelled = true;
    };
  }, [id, attempt]);

  const rematch = React.useCallback(async () => {
    setRematching(true);
    try {
      const updated = await api.opportunities.rematch(id);
      setDetail(updated);
      onPatch(id, {
        fit_score: updated.fit_score,
        fit_confidence: updated.fit_confidence,
        recommendation: updated.recommendation,
        eligibility: updated.eligibility,
      });
      toast.push("Re-scored against your profile", "success");
    } catch (err) {
      toast.push(messageOf(err, "Could not re-run the match."), "error");
    } finally {
      setRematching(false);
    }
  }, [id, onPatch, toast]);

  if (loadError) {
    return (
      <div className="px-5 py-4">
        <Alert tone="danger" title="Could not load the details">
          {loadError}
          <div className="mt-2">
            <Button
              size="xs"
              variant="secondary"
              onClick={() => {
                setLoadError(null);
                setAttempt((a) => a + 1);
              }}
            >
              Try again
            </Button>
          </div>
        </Alert>
      </div>
    );
  }

  if (loading || !detail) return <PanelSkeleton />;

  return (
    <>
      <MatchSection
        match={detail.match}
        onRematch={() => void rematch()}
        rematching={rematching}
      />
      <RequirementsSection
        required={detail.requirements}
        preferred={detail.preferred}
        inferred={detail.inferred}
      />
      <MaterialsSection
        documents={detail.documents_required}
        recommendations={detail.resume_recommendations}
        recommendedResumeId={detail.match?.recommended_resume_id ?? null}
      />
      <AboutSection detail={detail} />
      {detail.research && <ResearchSection research={detail.research} />}
      <SourceSection detail={detail} />
      {detail.notes && (
        <PanelSection title="Notes">
          <p className="whitespace-pre-line text-xs leading-relaxed text-[var(--text-secondary)]">
            {detail.notes}
          </p>
        </PanelSection>
      )}
    </>
  );
}

function PanelSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading details">
      <PanelSection title="Why you match">
        <Skeleton className="mb-2 h-3 w-2/3" />
        <Skeleton className="mb-3 h-3 w-5/6" />
        <div className="flex flex-col gap-2 rounded-[var(--radius-md)] border border-[var(--border)] p-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3">
              <Skeleton className="h-3 flex-1" />
              <Skeleton className="h-1 w-20" />
              <Skeleton className="h-3 w-7" />
            </div>
          ))}
        </div>
      </PanelSection>
      <PanelSection title="Requirements">
        <div className="flex flex-col gap-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-3 w-full" />
          ))}
        </div>
      </PanelSection>
      <PanelSection title="About the role">
        <Skeleton className="mb-2 h-3 w-full" />
        <Skeleton className="mb-2 h-3 w-11/12" />
        <Skeleton className="h-3 w-3/4" />
      </PanelSection>
    </div>
  );
}
