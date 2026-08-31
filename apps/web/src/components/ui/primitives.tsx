"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ Card */

export function Card({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-lg)]",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function SectionHeader({
  title,
  count,
  action,
  description,
  className,
}: {
  title: string;
  count?: number;
  action?: React.ReactNode;
  description?: string;
  className?: string;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-4 mb-3", className)}>
      <div className="min-w-0">
        <div className="flex items-baseline gap-2">
          <h2 className="text-[13px] font-semibold tracking-[-0.01em] text-[var(--text-primary)]">
            {title}
          </h2>
          {count !== undefined && (
            <span className="text-xs text-[var(--text-tertiary)] tnum">{count}</span>
          )}
        </div>
        {description && (
          <p className="text-xs text-[var(--text-tertiary)] mt-0.5">{description}</p>
        )}
      </div>
      {action}
    </div>
  );
}

/* ----------------------------------------------------------------- Badge */

type Tone = "neutral" | "accent" | "success" | "warn" | "danger" | "info";

const TONES: Record<Tone, string> = {
  neutral:
    "bg-[var(--bg-sunken)] text-[var(--text-secondary)] border-[var(--border-subtle)]",
  accent:
    "bg-[var(--accent-soft)] text-[var(--color-accent-700)] border-[var(--accent-border)]",
  success:
    "bg-[var(--color-success-50)] text-[var(--color-success-700)] border-[var(--color-success-200)]",
  warn: "bg-[var(--color-warn-50)] text-[var(--color-warn-700)] border-[var(--color-warn-200)]",
  danger:
    "bg-[var(--color-danger-50)] text-[var(--color-danger-700)] border-[var(--color-danger-200)]",
  info: "bg-[var(--color-info-50)] text-[var(--color-info-700)] border-[var(--color-info-200)]",
};

export function Badge({
  tone = "neutral",
  className,
  children,
}: {
  tone?: Tone;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 h-[18px] px-1.5 rounded-[var(--radius-xs)]",
        "border text-2xs font-medium whitespace-nowrap",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/** Bare text label — used where a bordered badge would add too much noise. */
export function Meta({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <span className={cn("text-xs text-[var(--text-tertiary)]", className)}>{children}</span>
  );
}

export function Dot({ className }: { className?: string }) {
  return <span className={cn("size-1.5 rounded-full shrink-0", className)} />;
}

/* ------------------------------------------------------------- EmptyState */

export function EmptyState({
  title,
  body,
  action,
  icon,
  className,
}: {
  title: string;
  body: string;
  action?: React.ReactNode;
  icon?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center px-6 py-14",
        className,
      )}
    >
      {icon && (
        <div className="mb-3 flex size-9 items-center justify-center rounded-[var(--radius-md)] bg-[var(--bg-sunken)] text-[var(--text-tertiary)]">
          {icon}
        </div>
      )}
      <h3 className="text-sm font-medium text-[var(--text-primary)]">{title}</h3>
      <p className="mt-1.5 max-w-[42ch] text-xs leading-relaxed text-[var(--text-tertiary)]">
        {body}
      </p>
      {action && <div className="mt-4 flex items-center gap-2">{action}</div>}
    </div>
  );
}

/* --------------------------------------------------------------- Skeleton */

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-[var(--radius-xs)] bg-[var(--bg-sunken)]",
        "after:absolute after:inset-0 after:-translate-x-full",
        "after:bg-gradient-to-r after:from-transparent after:via-black/[0.035] after:to-transparent",
        "after:animate-[trellis-shimmer_1.4s_infinite]",
        className,
      )}
    />
  );
}

export function TableSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <div className="divide-y divide-[var(--border-subtle)]">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-4 px-4 h-11">
          <Skeleton className="h-3 w-8" />
          <Skeleton className="h-3 flex-1 max-w-[280px]" />
          <Skeleton className="h-3 w-32" />
          <Skeleton className="ml-auto h-3 w-20" />
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ Tabs */

export function Tabs({
  tabs,
  value,
  onChange,
  className,
}: {
  tabs: { value: string; label: string; count?: number }[];
  value: string;
  onChange: (v: string) => void;
  className?: string;
}) {
  return (
    <div
      role="tablist"
      className={cn("flex items-center gap-0.5 border-b border-[var(--border)]", className)}
    >
      {tabs.map((tab) => {
        const active = tab.value === value;
        return (
          <button
            key={tab.value}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(tab.value)}
            className={cn(
              "relative -mb-px flex items-center gap-1.5 px-2.5 h-8 text-xs font-medium",
              "transition-colors duration-100 border-b-[1.5px]",
              active
                ? "text-[var(--text-primary)] border-[var(--accent)]"
                : "text-[var(--text-tertiary)] border-transparent hover:text-[var(--text-primary)]",
            )}
          >
            {tab.label}
            {tab.count !== undefined && (
              <span className="tnum text-[var(--text-tertiary)]">{tab.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  className,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "inline-flex items-center gap-0.5 p-0.5 rounded-[var(--radius-sm)] bg-[var(--bg-sunken)]",
        className,
      )}
    >
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "h-6 px-2 rounded-[var(--radius-xs)] text-xs font-medium transition-all duration-100",
            value === o.value
              ? "bg-[var(--bg)] text-[var(--text-primary)] shadow-xs"
              : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/* --------------------------------------------------------------- Tooltip */

export function Tooltip({
  content,
  children,
  side = "top",
}: {
  content: React.ReactNode;
  children: React.ReactNode;
  side?: "top" | "bottom";
}) {
  const [open, setOpen] = React.useState(false);
  if (!content) return <>{children}</>;
  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      {children}
      {open && (
        <span
          role="tooltip"
          className={cn(
            "pointer-events-none absolute left-1/2 z-50 -translate-x-1/2 animate-fade-in",
            "max-w-[280px] w-max rounded-[var(--radius-sm)] px-2 py-1.5",
            "bg-[var(--color-neutral-900)] text-[var(--color-neutral-50)]",
            "text-2xs leading-relaxed shadow-pop",
            side === "top" ? "bottom-full mb-1.5" : "top-full mt-1.5",
          )}
        >
          {content}
        </span>
      )}
    </span>
  );
}

/* ------------------------------------------------------------ ExternalLink */

export function ExternalLink({
  href,
  children,
  className,
}: {
  href: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={cn(
        "inline-flex items-center gap-1 text-[var(--accent)] hover:underline underline-offset-2",
        className,
      )}
      onClick={(e) => e.stopPropagation()}
    >
      {children}
      <svg className="size-2.5 shrink-0 opacity-70" viewBox="0 0 10 10" fill="none" aria-hidden>
        <path
          d="M3 1h6v6M9 1 1.5 8.5"
          stroke="currentColor"
          strokeWidth="1.3"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </a>
  );
}

/* ------------------------------------------------------------------ Alert */

export function Alert({
  tone = "neutral",
  title,
  children,
  className,
}: {
  tone?: Tone;
  title?: string;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-[var(--radius-md)] border px-3 py-2.5 text-xs leading-relaxed",
        TONES[tone],
        className,
      )}
    >
      {title && <div className="font-medium mb-0.5">{title}</div>}
      {children}
    </div>
  );
}
