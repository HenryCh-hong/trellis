import Link from "next/link";
import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Link that looks like a Button.
 *
 * The Overview's calls to action navigate, so they must be anchors — wrapping
 * a <button> in a <Link> would nest two interactive elements and break
 * keyboard and screen-reader behaviour.
 */
const BUTTON_BASE =
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap select-none font-medium " +
  "rounded-[var(--radius-sm)] transition-[background-color,color,box-shadow] duration-100";

const BUTTON_VARIANT = {
  primary:
    "bg-[var(--accent)] text-white shadow-xs hover:bg-[var(--accent-hover)] active:brightness-95",
  secondary:
    "border border-[var(--border)] bg-[var(--bg)] text-[var(--text-primary)] shadow-xs hover:bg-[var(--bg-hover)]",
} as const;

export function ButtonLink({
  href,
  variant = "secondary",
  className,
  children,
}: {
  href: string;
  variant?: keyof typeof BUTTON_VARIANT;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className={cn(BUTTON_BASE, "h-7 px-2.5 text-xs", BUTTON_VARIANT[variant], className)}
    >
      {children}
    </Link>
  );
}

/** The quiet "see everything" link that sits in a section header. */
export function SectionLink({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className="inline-flex shrink-0 items-center gap-1 text-xs text-[var(--text-tertiary)] transition-colors duration-100 hover:text-[var(--accent)]"
    >
      {children}
      <svg className="size-2.5 shrink-0" viewBox="0 0 10 10" fill="none" aria-hidden>
        <path
          d="m3.5 1.5 3.5 3.5-3.5 3.5"
          stroke="currentColor"
          strokeWidth="1.3"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </Link>
  );
}
