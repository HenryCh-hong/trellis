"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Long provenance prose — the basis for an inference, a fetch note — is kept
 * verbatim but folded away. Truncating it permanently would hide exactly the
 * part a sceptical reader needs.
 */
export function ExpandableText({
  text,
  lines = 3,
  className,
}: {
  text: string;
  lines?: 2 | 3 | 4;
  className?: string;
}) {
  const [open, setOpen] = React.useState(false);
  const clamp = { 2: "line-clamp-2", 3: "line-clamp-3", 4: "line-clamp-4" }[lines];
  // Roughly one folded line of prose; below it the toggle costs more than it saves.
  const foldable = text.length > lines * 90;

  return (
    <div className={className}>
      <p
        className={cn(
          "whitespace-pre-line text-xs leading-relaxed text-[var(--text-secondary)]",
          !open && foldable && clamp,
        )}
      >
        {text}
      </p>
      {foldable && (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="mt-1 text-2xs font-medium text-[var(--accent)] hover:underline"
        >
          {open ? "Show less" : "Show the full basis"}
        </button>
      )}
    </div>
  );
}
