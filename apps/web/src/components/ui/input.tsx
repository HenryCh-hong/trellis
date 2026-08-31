"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

const base =
  "w-full bg-[var(--bg)] text-[var(--text-primary)] border border-[var(--border)] " +
  "rounded-[var(--radius-sm)] transition-[border-color,box-shadow] duration-100 " +
  "placeholder:text-[var(--text-disabled)] " +
  "hover:border-[var(--border-strong)] " +
  "focus:outline-none focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent-soft)] " +
  "disabled:bg-[var(--bg-sunken)] disabled:text-[var(--text-disabled)]";

export const Input = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(({ className, ...props }, ref) => (
  <input ref={ref} className={cn(base, "h-8 px-2.5 text-sm", className)} {...props} />
));
Input.displayName = "Input";

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(base, "px-2.5 py-2 text-sm leading-relaxed resize-y min-h-[72px]", className)}
    {...props}
  />
));
Textarea.displayName = "Textarea";

export const Select = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(({ className, children, ...props }, ref) => (
  <div className="relative">
    <select
      ref={ref}
      className={cn(base, "h-8 pl-2.5 pr-7 text-sm appearance-none cursor-pointer", className)}
      {...props}
    >
      {children}
    </select>
    <svg
      className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 size-3 text-[var(--text-tertiary)]"
      viewBox="0 0 12 12"
      fill="none"
      aria-hidden
    >
      <path d="M3 4.5 6 7.5 9 4.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  </div>
));
Select.displayName = "Select";

export function Field({
  label,
  hint,
  error,
  required,
  children,
  className,
}: {
  label: string;
  hint?: string;
  error?: string | null;
  required?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <label className={cn("flex flex-col gap-1.5", className)}>
      <span className="text-xs font-medium text-[var(--text-secondary)]">
        {label}
        {required && <span className="text-[var(--color-danger-500)]"> *</span>}
      </span>
      {children}
      {error ? (
        <span className="text-xs text-[var(--color-danger-600)]">{error}</span>
      ) : hint ? (
        <span className="text-xs text-[var(--text-tertiary)]">{hint}</span>
      ) : null}
    </label>
  );
}

export function Checkbox({
  className,
  label,
  "aria-label": ariaLabel,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement> & { label?: React.ReactNode }) {
  // When the visible label is a node rather than a string, the input still needs
  // its own accessible name or it is announced as an unnamed checkbox.
  const fallbackName =
    ariaLabel ?? (typeof label === "string" ? label : undefined);
  return (
    <label className="inline-flex items-center gap-2 cursor-pointer select-none">
      <input
        type="checkbox"
        aria-label={fallbackName}
        className={cn(
          "size-3.5 rounded-[3px] border border-[var(--border-strong)] bg-[var(--bg)]",
          "appearance-none cursor-pointer transition-colors duration-100",
          "checked:bg-[var(--accent)] checked:border-[var(--accent)]",
          "checked:bg-[url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 14 14%22><path d=%22M3 7.2l2.6 2.6L11 4.4%22 fill=%22none%22 stroke=%22white%22 stroke-width=%222%22 stroke-linecap=%22round%22 stroke-linejoin=%22round%22/></svg>')] bg-center bg-no-repeat",
          className,
        )}
        {...props}
      />
      {label && <span className="text-sm text-[var(--text-primary)]">{label}</span>}
    </label>
  );
}

export function Switch({
  checked,
  onCheckedChange,
  disabled,
  label,
}: {
  checked: boolean;
  onCheckedChange: (v: boolean) => void;
  disabled?: boolean;
  label?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        "relative h-4 w-7 shrink-0 rounded-full transition-colors duration-150 disabled:opacity-50",
        checked ? "bg-[var(--accent)]" : "bg-[var(--color-neutral-300)]",
      )}
    >
      <span
        className={cn(
          "absolute top-0.5 left-0.5 size-3 rounded-full bg-white shadow-xs",
          "transition-transform duration-150 ease-[var(--ease-out-quart)]",
          checked && "translate-x-3",
        )}
      />
    </button>
  );
}
