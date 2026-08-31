"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { Button } from "./button";

/**
 * Right-hand detail panel.
 *
 * Chosen over a modal because the list stays visible and keyboard-navigable
 * behind it — you can arrow through rows and watch the panel update.
 */
export function SidePanel({
  open,
  onClose,
  title,
  subtitle,
  actions,
  children,
  footer,
  width = "wide",
}: {
  open: boolean;
  onClose: () => void;
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: "wide" | "narrow";
}) {
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-[var(--color-neutral-950)]/[0.08] animate-fade-in"
        onClick={onClose}
        aria-hidden
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === "string" ? title : "Details"}
        className={cn(
          "fixed right-0 top-0 z-50 flex h-full flex-col bg-[var(--bg)]",
          "border-l border-[var(--border)] shadow-panel animate-slide-in",
          width === "wide" ? "w-full max-w-[620px]" : "w-full max-w-[440px]",
        )}
      >
        <header className="flex items-start gap-3 border-b border-[var(--border)] px-5 py-4">
          <div className="min-w-0 flex-1">
            {title}
            {subtitle}
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {actions}
            <Button
              variant="ghost"
              size="sm"
              onClick={onClose}
              aria-label="Close panel"
              className="px-1.5"
            >
              <svg className="size-3.5" viewBox="0 0 14 14" fill="none" aria-hidden>
                <path d="M3.5 3.5l7 7M10.5 3.5l-7 7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
              </svg>
            </Button>
          </div>
        </header>

        <div className="scrollbar-thin flex-1 overflow-y-auto overscroll-contain">
          {children}
        </div>

        {footer && (
          <footer className="border-t border-[var(--border)] bg-[var(--bg-subtle)] px-5 py-3">
            {footer}
          </footer>
        )}
      </aside>
    </>
  );
}

export function PanelSection({
  title,
  action,
  children,
  className,
}: {
  title?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("border-b border-[var(--border-subtle)] px-5 py-4", className)}>
      {title && (
        <div className="mb-2.5 flex items-center justify-between gap-2">
          <h3 className="text-2xs font-semibold uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
            {title}
          </h3>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function KeyValue({
  items,
  columns = 2,
}: {
  items: { label: string; value: React.ReactNode }[];
  columns?: 1 | 2 | 3;
}) {
  return (
    <dl
      className={cn(
        "grid gap-x-6 gap-y-3",
        columns === 1 && "grid-cols-1",
        columns === 2 && "grid-cols-2",
        columns === 3 && "grid-cols-3",
      )}
    >
      {items.map((item) => (
        <div key={item.label} className="min-w-0">
          <dt className="text-2xs uppercase tracking-[0.04em] text-[var(--text-tertiary)]">
            {item.label}
          </dt>
          <dd className="mt-0.5 text-sm text-[var(--text-primary)] break-words">
            {item.value ?? "—"}
          </dd>
        </div>
      ))}
    </dl>
  );
}
