"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Token input for skills, interests, keywords and locations.
 *
 * Enter or comma commits; Backspace on an empty field removes the last token.
 * Suggestions are a real listbox so it is navigable without a mouse.
 */
export function TagInput({
  values,
  onAdd,
  onRemove,
  suggestions = [],
  placeholder = "Add and press Enter",
  addMoreLabel = "Add another…",
  ariaLabel,
  id,
  disabled,
}: {
  values: { id: string; label: string; hint?: string }[];
  onAdd: (label: string) => void;
  onRemove: (id: string) => void;
  suggestions?: string[];
  placeholder?: string;
  addMoreLabel?: string;
  ariaLabel?: string;
  id?: string;
  disabled?: boolean;
}) {
  const [draft, setDraft] = React.useState("");
  const [active, setActive] = React.useState(-1);
  const listId = React.useId();

  const taken = new Set(values.map((v) => v.label.toLowerCase()));
  const matches = draft.trim()
    ? suggestions
        .filter(
          (s) => s.toLowerCase().includes(draft.trim().toLowerCase()) && !taken.has(s.toLowerCase()),
        )
        .slice(0, 6)
    : [];

  const commit = (label: string) => {
    const clean = label.trim().replace(/,$/, "");
    if (!clean || taken.has(clean.toLowerCase())) {
      setDraft("");
      return;
    }
    onAdd(clean);
    setDraft("");
    setActive(-1);
  };

  return (
    <div className="relative">
      <div
        className={cn(
          "flex min-h-8 flex-wrap items-center gap-1.5 rounded-[var(--radius-sm)] border p-1.5",
          "border-[var(--border)] bg-[var(--bg)] transition-colors",
          "focus-within:border-[var(--accent)] focus-within:ring-2 focus-within:ring-[var(--accent-soft)]",
          disabled && "opacity-60",
        )}
      >
        {values.map((v) => (
          <span
            key={v.id}
            className="inline-flex items-center gap-1 rounded-[var(--radius-xs)] border border-[var(--border-subtle)] bg-[var(--bg-sunken)] px-1.5 py-0.5 text-2xs"
            title={v.hint}
          >
            {v.label}
            {v.hint && <span className="text-[var(--text-tertiary)]">· {v.hint}</span>}
            <button
              type="button"
              onClick={() => onRemove(v.id)}
              aria-label={`Remove ${v.label}`}
              disabled={disabled}
              className="ml-0.5 text-[var(--text-tertiary)] hover:text-[var(--color-danger-600)]"
            >
              <svg className="size-2.5" viewBox="0 0 10 10" fill="none" aria-hidden>
                <path d="M2 2l6 6M8 2l-6 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </button>
          </span>
        ))}

        <input
          id={id}
          value={draft}
          disabled={disabled}
          onChange={(e) => {
            setDraft(e.target.value);
            setActive(-1);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              commit(active >= 0 && matches[active] ? matches[active] : draft);
            } else if (e.key === "Backspace" && !draft && values.length) {
              onRemove(values[values.length - 1].id);
            } else if (e.key === "ArrowDown" && matches.length) {
              e.preventDefault();
              setActive((i) => (i + 1) % matches.length);
            } else if (e.key === "ArrowUp" && matches.length) {
              e.preventDefault();
              setActive((i) => (i <= 0 ? matches.length - 1 : i - 1));
            } else if (e.key === "Escape") {
              setActive(-1);
            }
          }}
          // Keep an affordance once tags exist. Blanking the placeholder left
          // no hint that the field still accepts input.
          placeholder={values.length ? addMoreLabel : placeholder}
          role="combobox"
          aria-label={ariaLabel ?? placeholder}
          aria-expanded={matches.length > 0}
          aria-controls={listId}
          aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
          className="min-w-[120px] flex-1 bg-transparent px-1 text-sm outline-none placeholder:text-[var(--text-disabled)]"
        />
      </div>

      {matches.length > 0 && (
        <ul
          id={listId}
          role="listbox"
          className="absolute z-20 mt-1 w-full overflow-hidden rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg)] shadow-pop"
        >
          {matches.map((s, i) => (
            <li
              key={s}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => {
                e.preventDefault();
                commit(s);
              }}
              className={cn(
                "cursor-pointer px-2.5 py-1.5 text-xs",
                i === active ? "bg-[var(--bg-selected)]" : "hover:bg-[var(--bg-hover)]",
              )}
            >
              {s}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export const SUGGESTED_INTERESTS = [
  "LLMs", "AI agents", "HCI", "computer vision", "robotics", "multimodal AI",
  "NLP", "ML systems", "AI + education", "reinforcement learning", "AI safety",
  "human-AI interaction", "speech and audio", "generative models",
  "computational social science", "AI for health", "graphics", "embodied AI",
];

export const SUGGESTED_SKILLS = [
  "Python", "PyTorch", "JavaScript", "TypeScript", "React", "C++", "Java",
  "SQL", "Git", "Linux", "LaTeX", "MATLAB", "R", "NumPy", "pandas",
  "scikit-learn", "Hugging Face", "Docker", "AWS", "ROS", "Figma",
  "data analysis", "statistics", "technical writing", "tutoring",
  "public speaking", "customer service", "event planning",
];
