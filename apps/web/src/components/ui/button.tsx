"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "subtle" | "danger" | "link";
type Size = "xs" | "sm" | "md";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-[var(--accent)] text-white shadow-xs hover:bg-[var(--accent-hover)] active:brightness-95 disabled:bg-[var(--color-neutral-300)]",
  secondary:
    "bg-[var(--bg)] text-[var(--text-primary)] border border-[var(--border)] shadow-xs hover:bg-[var(--bg-hover)] active:bg-[var(--bg-active)]",
  subtle:
    "bg-[var(--bg-sunken)] text-[var(--text-primary)] hover:bg-[var(--bg-active)]",
  ghost:
    "text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]",
  danger:
    "bg-[var(--bg)] text-[var(--color-danger-600)] border border-[var(--color-danger-200)] hover:bg-[var(--color-danger-50)]",
  link: "text-[var(--accent)] hover:underline underline-offset-2 px-0",
};

const SIZES: Record<Size, string> = {
  xs: "h-6 px-2 text-2xs gap-1 rounded-[var(--radius-xs)]",
  sm: "h-7 px-2.5 text-xs gap-1.5 rounded-[var(--radius-sm)]",
  md: "h-8 px-3 text-sm gap-1.5 rounded-[var(--radius-sm)]",
};

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "secondary", size = "md", loading, disabled, children, ...props }, ref) => (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        "inline-flex items-center justify-center font-medium whitespace-nowrap",
        "transition-[background-color,color,box-shadow,opacity] duration-100",
        "disabled:opacity-55 disabled:pointer-events-none select-none",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...props}
    >
      {loading && <Spinner />}
      {children}
    </button>
  ),
);
Button.displayName = "Button";

export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      className={cn("size-3 animate-spin", className)}
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden
    >
      <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2" />
      <path d="M14.5 8A6.5 6.5 0 0 0 8 1.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
