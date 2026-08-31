"use client";

/**
 * "Can I apply right now?" — rendered identically on the opportunity panel and
 * on the application kit page.
 *
 * Every value here comes from the server's `ApplicationReadiness`. Nothing is
 * recomputed in the browser, which is the whole point: two screens that each
 * did their own arithmetic would eventually tell the student two different
 * stories about the same application.
 */

import * as React from "react";
import { Dot, Tooltip } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";
import type { ApplicationReadiness, ReadinessItem, ReadinessState } from "@/lib/types";

const STATE: Record<ReadinessState, { dot: string; text: string; label: string }> = {
  ready: {
    dot: "bg-[var(--color-success-500)]",
    text: "text-[var(--text-primary)]",
    label: "Ready",
  },
  attention: {
    dot: "bg-[var(--color-warn-500)]",
    text: "text-[var(--color-warn-700)]",
    label: "Needs you",
  },
  blocked: {
    dot: "bg-[var(--color-danger-500)]",
    text: "text-[var(--color-danger-700)]",
    label: "Blocked",
  },
  // Not a soft "attention": we could not establish the fact, and saying so is
  // more use than a tick that means nothing.
  unknown: {
    dot: "bg-[var(--color-neutral-300)]",
    text: "text-[var(--text-tertiary)]",
    label: "Not known",
  },
};

function Mark({ state }: { state: ReadinessState }) {
  if (state === "ready") {
    return (
      <span
        aria-hidden
        className="inline-flex w-3 shrink-0 justify-center text-2xs leading-none text-[var(--color-success-600)]"
      >
        ✓
      </span>
    );
  }
  return (
    <span className="inline-flex w-3 shrink-0 justify-center">
      <Dot className={STATE[state].dot} />
    </span>
  );
}

function Row({
  item,
  onJump,
}: {
  item: ReadinessItem;
  /** Present only when this row has somewhere to send you. */
  onJump?: (item: ReadinessItem) => void;
}) {
  const tone = STATE[item.state];
  const body = (
    <>
      <Mark state={item.state} />
      <span className="min-w-0 shrink-0 basis-[40%] truncate text-left text-xs text-[var(--text-secondary)]">
        {item.label}
      </span>
      <span className={cn("min-w-0 flex-1 truncate text-left text-xs", tone.text)}>
        {item.detail}
      </span>
    </>
  );

  // A row is a button only when pressing it does something. "Deadline" and
  // "Application link" are facts, not tasks, so they stay plain text.
  const interactive = Boolean(onJump) && item.state !== "ready";
  const content = interactive ? (
    <button
      type="button"
      onClick={() => onJump?.(item)}
      className="flex w-full items-baseline gap-2 rounded-[var(--radius-xs)] py-1 text-left hover:bg-[var(--bg-hover)]"
    >
      {body}
    </button>
  ) : (
    <div className="flex w-full items-baseline gap-2 py-1">{body}</div>
  );

  return item.note ? (
    <Tooltip content={`${tone.label} — ${item.note}`}>{content}</Tooltip>
  ) : (
    content
  );
}

export function ReadinessList({
  readiness,
  onJump,
  canJump,
  className,
}: {
  readiness: ApplicationReadiness;
  /** Called when a row that still needs work is clicked. */
  onJump?: (item: ReadinessItem) => void;
  /** Which rows have a destination. Rows without one are never clickable. */
  canJump?: (item: ReadinessItem) => boolean;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col", className)}>
      {readiness.items.map((item) => (
        <Row
          key={item.key}
          item={item}
          onJump={onJump && (!canJump || canJump(item)) ? onJump : undefined}
        />
      ))}
    </div>
  );
}

/**
 * The one line that says what happens next. It is never "Apply": Trellis does
 * not submit, and the label comes from the server so it cannot say otherwise.
 */
export function ReadinessSummary({ readiness }: { readiness: ApplicationReadiness }) {
  if (readiness.ready) {
    return (
      <p className="text-xs text-[var(--color-success-700)]">
        Everything Trellis can check is ready. You still submit on the site yourself.
      </p>
    );
  }
  const count = readiness.blocking.length;
  return (
    <p className="text-xs text-[var(--text-secondary)]">
      {count === 0
        ? "Nothing is blocking this yet."
        : count === 1
          ? `One thing left: ${readiness.blocking[0].replace(/\.$/, "").toLowerCase()}.`
          : `${count} things to finish before this is ready to review.`}
    </p>
  );
}
