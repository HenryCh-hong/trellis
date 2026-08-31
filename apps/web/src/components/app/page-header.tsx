import * as React from "react";
import { cn } from "@/lib/utils";

export function PageHeader({
  title,
  description,
  actions,
  className,
  children,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <header
      className={cn(
        "sticky top-0 z-20 border-b border-[var(--border)] bg-[var(--bg)]/85 backdrop-blur-sm",
        className,
      )}
    >
      <div className="flex min-h-12 items-center gap-4 px-5 py-2.5">
        <div className="min-w-0 flex-1">
          <h1 className="text-[15px] font-semibold tracking-[-0.015em] text-[var(--text-primary)]">
            {title}
          </h1>
          {description && (
            <p className="mt-0.5 text-xs text-[var(--text-tertiary)]">{description}</p>
          )}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      {children}
    </header>
  );
}
