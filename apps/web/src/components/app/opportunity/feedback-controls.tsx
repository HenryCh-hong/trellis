"use client";

/**
 * The quiet controls: "Interested", "Not relevant", "Already applied", "Hide".
 *
 * Three rules shape how these look and behave.
 *
 * 1. They are not a rating. There is no scale, no stars and no score to move —
 *    four verbs, each of which does one small, stated thing.
 * 2. The state is never hidden behind hover. The *controls* fade in on the row,
 *    but once you have said something the row says so at all times, because a
 *    list that quietly reorders itself is a list you cannot trust.
 * 3. Undo is part of the action, not a thing to go and find. Every change puts
 *    an Undo in the toast, and a marked row carries its own × as well.
 */

import * as React from "react";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api, ApiError } from "@/lib/api";
import {
  REASONS,
  REASON_LABEL,
  SIGNAL_EFFECT,
  SIGNAL_LABEL,
} from "@/lib/feedback";
import { cn } from "@/lib/utils";
import type {
  FeedbackReason,
  FeedbackSignal,
  OpportunityFeedback,
  OpportunityListItem,
} from "@/lib/types";

type Patch = (id: string, patch: Partial<OpportunityListItem>) => void;

function messageOf(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

/**
 * One place that writes a signal, so the row, the panel and the Overview can
 * never end up disagreeing about what you said.
 *
 * The write is optimistic and rolled back on failure: the row must react at
 * once, and a request that fails must leave no trace of a state you never got.
 */
function useFeedbackWriter(item: OpportunityListItem, onPatch: Patch) {
  const toast = useToast();
  const [busy, setBusy] = React.useState(false);
  const id = item.id;
  const current = item.feedback;

  // Plain functions rather than memoised ones: `write` calls itself to undo,
  // and nothing downstream depends on the identity of these staying stable.
  async function write(
    next: OpportunityFeedback | null,
    previous: OpportunityFeedback | null,
    announce: string | null,
  ): Promise<void> {
    onPatch(id, { feedback: next });
    setBusy(true);
    try {
      if (next === null) {
        await api.opportunities.clearFeedback(id);
      } else {
        const saved = await api.opportunities.feedback(id, {
          signal: next.signal,
          ...(next.reason ? { reason: next.reason } : {}),
          ...(next.note ? { note: next.note } : {}),
        });
        onPatch(id, { feedback: saved });
      }
      if (announce) {
        toast.push(announce, "default", {
          label: "Undo",
          // Undo restores exactly what was there before, including "nothing",
          // and says nothing itself — an undo that toasts is a loop.
          onClick: () => void write(previous, next, null),
        });
      }
    } catch (err) {
      onPatch(id, { feedback: previous });
      toast.push(messageOf(err, "Could not record that. Nothing was changed."), "error");
    } finally {
      setBusy(false);
    }
  }

  function mark(signal: FeedbackSignal, reason: FeedbackReason | null = null): void {
    const next: OpportunityFeedback = {
      signal,
      reason,
      note: null,
      created_at: new Date().toISOString(),
    };
    const detail = reason ? ` (${REASON_LABEL[reason].toLowerCase()})` : "";
    void write(next, current, `${SIGNAL_LABEL[signal]}${detail} · ${SIGNAL_EFFECT[signal]}`);
  }

  function clear(): void {
    if (!current) return;
    void write(null, current, `${SIGNAL_LABEL[current.signal]} removed.`);
  }

  return { busy, mark, clear };
}

/* ------------------------------------------------------------------ icons */

function Icon({ path, className }: { path: React.ReactNode; className?: string }) {
  return (
    <svg
      viewBox="0 0 14 14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.3"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cn("size-3.5", className)}
      aria-hidden
    >
      {path}
    </svg>
  );
}

/** A bookmark: keep this one in view. Deliberately not a star or a heart. */
const INTERESTED_ICON = <path d="M4 2.5h6v9L7 9.2 4 11.5v-9z" />;
/** A minus in a circle: less of this one. Demotion, not deletion. */
const NOT_RELEVANT_ICON = (
  <>
    <circle cx="7" cy="7" r="4.75" />
    <path d="M4.9 7h4.2" />
  </>
);
/** A tick: you have already done this one, elsewhere. */
const APPLIED_ICON = <path d="M3 7.4l2.6 2.6L11 4.4" />;
/** An eye with a stroke through it. */
const HIDE_ICON = (
  <>
    <path d="M2 7s2-3.2 5-3.2S12 7 12 7s-2 3.2-5 3.2S2 7 2 7z" />
    <path d="M2.6 11.4L11.4 2.6" />
  </>
);

/* --------------------------------------------------------------- controls */

interface ControlProps {
  item: OpportunityListItem;
  onPatch: Patch;
}

/**
 * The compact form used on a table row. Hidden until the row is hovered or
 * something inside it takes focus, so the list stays quiet at rest — but always
 * reachable by keyboard, which is why `focus-within` is here too.
 */
export function RowFeedbackControls({
  item,
  onPatch,
  compact = false,
}: ControlProps & { compact?: boolean }) {
  const { busy, mark, clear } = useFeedbackWriter(item, onPatch);
  const [reasonsOpen, setReasonsOpen] = React.useState(false);

  if (item.feedback) {
    return <FeedbackTag feedback={item.feedback} busy={busy} onClear={clear} />;
  }

  // Nothing to reveal on a touch device, where there is no hover: the compact
  // row reports state only, and the panel is where the decision is made.
  if (compact) return null;

  return (
    <div
      // Click anywhere in here must not also open the detail panel: these are
      // decisions about the row, not a way into it.
      onClick={(e) => e.stopPropagation()}
      className={cn(
        "flex items-center justify-end gap-0.5 opacity-0 transition-opacity duration-100",
        "group-hover:opacity-100 focus-within:opacity-100",
        reasonsOpen && "opacity-100",
      )}
    >
      <IconButton
        label="Interested"
        hint={SIGNAL_EFFECT.interested}
        icon={INTERESTED_ICON}
        disabled={busy}
        onClick={() => mark("interested")}
      />
      <ReasonPicker
        open={reasonsOpen}
        onOpenChange={setReasonsOpen}
        disabled={busy}
        onPick={(reason) => mark("not_relevant", reason)}
        trigger={
          <IconButton
            label="Not relevant"
            hint={SIGNAL_EFFECT.not_relevant}
            icon={NOT_RELEVANT_ICON}
            disabled={busy}
            onClick={() => setReasonsOpen((v) => !v)}
            expanded={reasonsOpen}
          />
        }
      />
      <IconButton
        label="Already applied"
        hint={SIGNAL_EFFECT.already_applied}
        icon={APPLIED_ICON}
        disabled={busy}
        onClick={() => mark("already_applied")}
      />
      <IconButton
        label="Hide"
        hint={SIGNAL_EFFECT.hidden}
        icon={HIDE_ICON}
        disabled={busy}
        onClick={() => mark("hidden")}
      />
    </div>
  );
}

function IconButton({
  label,
  hint,
  icon,
  onClick,
  disabled,
  expanded,
}: {
  label: string;
  hint: string;
  icon: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  expanded?: boolean;
}) {
  return (
    <Tooltip content={`${label} — ${hint}`}>
      <button
        type="button"
        aria-label={label}
        aria-expanded={expanded}
        disabled={disabled}
        onClick={onClick}
        className={cn(
          "flex size-6 items-center justify-center rounded-[var(--radius-xs)]",
          "text-[var(--text-tertiary)] transition-colors duration-100",
          "hover:bg-[var(--bg-active)] hover:text-[var(--text-primary)]",
          "disabled:pointer-events-none disabled:opacity-40",
          expanded && "bg-[var(--bg-active)] text-[var(--text-primary)]",
        )}
      >
        <Icon path={icon} />
      </button>
    </Tooltip>
  );
}

/**
 * The reason list. Five choices and a way to skip them: a reason is useful to
 * record, and never worth blocking the action for.
 */
function ReasonPicker({
  open,
  onOpenChange,
  onPick,
  trigger,
  disabled,
  align = "right",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPick: (reason: FeedbackReason | null) => void;
  trigger: React.ReactNode;
  disabled?: boolean;
  align?: "left" | "right";
}) {
  const ref = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) onOpenChange(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      // The list owns Escape too (it closes the panel), so stop here.
      e.stopPropagation();
      onOpenChange(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [open, onOpenChange]);

  const choose = (reason: FeedbackReason | null) => {
    onOpenChange(false);
    onPick(reason);
  };

  return (
    <div ref={ref} className="relative">
      {trigger}
      {open && !disabled && (
        <div
          role="menu"
          aria-label="Why is this not relevant?"
          className={cn(
            "absolute top-full z-50 mt-1 w-[176px] animate-rise overflow-hidden",
            "rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg)] shadow-pop",
            align === "right" ? "right-0" : "left-0",
          )}
        >
          <p className="border-b border-[var(--border-subtle)] px-2.5 py-1.5 text-2xs text-[var(--text-tertiary)]">
            Why? Only this one moves.
          </p>
          {REASONS.map((reason) => (
            <button
              key={reason}
              type="button"
              role="menuitem"
              onClick={() => choose(reason)}
              className="block w-full px-2.5 py-1.5 text-left text-xs text-[var(--text-secondary)] transition-colors duration-100 hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
            >
              {REASON_LABEL[reason]}
            </button>
          ))}
          <button
            type="button"
            role="menuitem"
            onClick={() => choose(null)}
            className="block w-full border-t border-[var(--border-subtle)] px-2.5 py-1.5 text-left text-xs text-[var(--text-tertiary)] transition-colors duration-100 hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
          >
            No reason
          </button>
        </div>
      )}
    </div>
  );
}

/** What you said, stated plainly, with the undo attached to it. */
export function FeedbackTag({
  feedback,
  busy,
  onClear,
}: {
  feedback: OpportunityFeedback;
  busy: boolean;
  onClear: () => void;
}) {
  const detail = feedback.reason ? ` · ${REASON_LABEL[feedback.reason]}` : "";
  return (
    <span
      onClick={(e) => e.stopPropagation()}
      className={cn(
        "inline-flex h-[20px] max-w-full items-center gap-1 rounded-[var(--radius-xs)] pl-1.5 pr-1",
        "border border-[var(--border)] bg-[var(--bg-subtle)]",
        "text-2xs font-medium text-[var(--text-secondary)]",
      )}
    >
      <Tooltip content={`${SIGNAL_LABEL[feedback.signal]}${detail} — ${SIGNAL_EFFECT[feedback.signal]}`}>
        <span className="truncate">{SIGNAL_LABEL[feedback.signal]}</span>
      </Tooltip>
      <Tooltip content="Undo — clears this and puts the row back exactly as it was.">
        <button
          type="button"
          aria-label={`Undo ${SIGNAL_LABEL[feedback.signal].toLowerCase()}`}
          disabled={busy}
          onClick={onClear}
          className="shrink-0 rounded-[2px] p-[1px] opacity-70 transition-opacity hover:opacity-100 disabled:pointer-events-none disabled:opacity-30"
        >
          <svg className="size-2.5" viewBox="0 0 10 10" fill="none" aria-hidden>
            <path
              d="M2.5 2.5l5 5M7.5 2.5l-5 5"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeLinecap="round"
            />
          </svg>
        </button>
      </Tooltip>
    </span>
  );
}

/* ------------------------------------------------------------------ panel */

/**
 * The panel form. Same four decisions, written out in words, plus the sentence
 * saying what the current one actually did.
 */
export function PanelFeedbackControls({ item, onPatch }: ControlProps) {
  const { busy, mark, clear } = useFeedbackWriter(item, onPatch);
  const [reasonsOpen, setReasonsOpen] = React.useState(false);
  const current = item.feedback?.signal ?? null;

  const choice = (signal: FeedbackSignal, onClick: () => void, expanded?: boolean) => (
    <Button
      key={signal}
      size="xs"
      variant={current === signal ? "primary" : "secondary"}
      disabled={busy}
      aria-pressed={current === signal}
      aria-expanded={expanded}
      onClick={onClick}
    >
      {SIGNAL_LABEL[signal]}
    </Button>
  );

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {choice("interested", () => mark("interested"))}
        <ReasonPicker
          align="left"
          open={reasonsOpen}
          onOpenChange={setReasonsOpen}
          disabled={busy}
          onPick={(reason) => mark("not_relevant", reason)}
          trigger={choice("not_relevant", () => setReasonsOpen((v) => !v), reasonsOpen)}
        />
        {choice("already_applied", () => mark("already_applied"))}
        {choice("hidden", () => mark("hidden"))}
        {item.feedback && (
          <Button size="xs" variant="ghost" disabled={busy} onClick={clear}>
            Undo
          </Button>
        )}
      </div>

      <p className="text-xs leading-relaxed text-[var(--text-tertiary)]">
        {item.feedback ? (
          <>
            <span className="text-[var(--text-secondary)]">
              {SIGNAL_LABEL[item.feedback.signal]}
              {item.feedback.reason ? ` · ${REASON_LABEL[item.feedback.reason]}` : ""}.
            </span>{" "}
            {SIGNAL_EFFECT[item.feedback.signal]}{" "}
            {item.feedback.reason
              ? "The reason is recorded against this posting only — it changes nothing about the topic."
              : ""}
          </>
        ) : (
          "Nothing recorded. Whatever you choose applies to this one opportunity, is reversible, and never changes how anything else is ranked."
        )}
      </p>
    </div>
  );
}
