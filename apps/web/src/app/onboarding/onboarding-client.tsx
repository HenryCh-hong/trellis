"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

import { SUGGESTED_INTERESTS, SUGGESTED_SKILLS, TagInput } from "@/components/app/tag-input";
import { Button } from "@/components/ui/button";
import { Checkbox, Field, Input } from "@/components/ui/input";
import { Alert, Card, Tooltip } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import type { SearchRunSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

const STEPS = ["University", "Interests", "Skills", "Resumes", "Search"] as const;

const JOB_TYPES = [
  { value: "on_campus", label: "On-campus jobs", hint: "Library, IT, dining, campus rec" },
  { value: "part_time", label: "Part-time jobs", hint: "Hourly work near campus" },
  { value: "research_opening", label: "Research openings", hint: "Programmes with an application" },
  { value: "research_outreach", label: "Lab outreach", hint: "Labs worth emailing with no posting" },
];

interface Draft {
  university: string;
  campus: string;
  major: string;
  degree: string;
  graduation_year: string;
  interests: string[];
  skills: string[];
  job_types: string[];
  hours_min: string;
  hours_max: string;
}

export function OnboardingClient() {
  const router = useRouter();
  const [step, setStep] = React.useState(0);
  const [draft, setDraft] = React.useState<Draft>({
    university: "Stanford University",
    campus: "",
    major: "",
    degree: "BS",
    graduation_year: "",
    interests: [],
    skills: [],
    job_types: ["on_campus", "research_opening", "research_outreach"],
    hours_min: "8",
    hours_max: "15",
  });
  const [files, setFiles] = React.useState<{ file: File; label: string }[]>([]);
  const [submitting, setSubmitting] = React.useState(false);
  const [runs, setRuns] = React.useState<SearchRunSummary[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const fileRef = React.useRef<HTMLInputElement>(null);

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((d) => ({ ...d, [key]: value }));

  const valid = React.useMemo(() => {
    if (step === 0) return draft.university.trim().length > 1;
    if (step === 1) return draft.interests.length > 0;
    if (step === 4) return draft.job_types.length > 0;
    return true;
  }, [step, draft]);

  const next = () => {
    if (!valid) return;
    setStep((s) => Math.min(s + 1, STEPS.length - 1));
  };

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      const { run_ids } = await api.profile.onboard({
        university: draft.university.trim(),
        campus: draft.campus.trim() || null,
        major: draft.major.trim() || null,
        degree: draft.degree.trim() || null,
        graduation_year: draft.graduation_year ? Number(draft.graduation_year) : null,
        interests: draft.interests,
        skills: draft.skills,
        job_types: draft.job_types,
        hours_per_week_min: draft.hours_min ? Number(draft.hours_min) : null,
        hours_per_week_max: draft.hours_max ? Number(draft.hours_max) : null,
        run_discovery: true,
      });

      for (const { file, label } of files) {
        try {
          await api.resumes.upload(file, label);
        } catch {
          // A failed upload must not block onboarding; Resumes page can retry.
        }
      }

      if (run_ids.length === 0) {
        router.push("/");
        return;
      }
      await pollRuns(run_ids);
      router.push("/");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not finish setting up.");
      setSubmitting(false);
    }
  }

  /** Show the run's REAL step text. Never a fake progress bar. */
  async function pollRuns(ids: string[]) {
    for (let attempt = 0; attempt < 40; attempt++) {
      let all: SearchRunSummary[] = [];
      try {
        all = await api.searches.runs();
      } catch {
        break;
      }
      const mine = all.filter((r) => ids.includes(r.id));
      setRuns(mine);
      if (mine.length > 0 && mine.every((r) => r.status !== "running" && r.status !== "queued")) {
        return;
      }
      await new Promise((r) => setTimeout(r, 1200));
    }
  }

  if (submitting) {
    return (
      <Shell step={STEPS.length - 1}>
        <h1 className="text-xl font-semibold tracking-[-0.02em]">Finding your first opportunities</h1>
        <p className="mt-1 text-xs text-[var(--text-tertiary)]">
          This reads real pages, so it takes a moment.
        </p>
        <Card className="mt-5 p-4">
          {runs.length === 0 ? (
            <p className="text-xs text-[var(--text-secondary)]">Starting…</p>
          ) : (
            <ul className="space-y-2">
              {runs.flatMap((run) =>
                (run.steps.length ? run.steps : [{ step: run.kind, detail: "Starting…", status: "ok" }]).map(
                  (s, i) => (
                    <li key={`${run.id}-${i}`} className="flex items-start gap-2 text-xs">
                      <span
                        className={cn(
                          "mt-[6px] size-1.5 shrink-0 rounded-full",
                          s.status === "error"
                            ? "bg-[var(--color-danger-500)]"
                            : s.status === "skipped"
                              ? "bg-[var(--color-neutral-400)]"
                              : "bg-[var(--color-success-500)]",
                        )}
                      />
                      <span className="text-[var(--text-secondary)]">{String(s.detail)}</span>
                    </li>
                  ),
                ),
              )}
            </ul>
          )}
        </Card>
        {error && (
          <Alert tone="danger" className="mt-4" title="Something went wrong">
            {error}
          </Alert>
        )}
        <Button variant="ghost" size="sm" className="mt-4" onClick={() => router.push("/")}>
          Continue to the dashboard
        </Button>
      </Shell>
    );
  }

  return (
    <Shell step={step}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (step === STEPS.length - 1) submit();
          else next();
        }}
      >
        {step === 0 && (
          <>
            <StepTitle
              title="Where do you study?"
              hint="This decides which departments, job boards and faculty directories we search."
            />
            <div className="space-y-3">
              <Field label="University" required>
                <Input
                  autoFocus
                  value={draft.university}
                  onChange={(e) => set("university", e.target.value)}
                />
              </Field>
              <Field label="Campus" hint="Optional — helps with location matching.">
                <Input value={draft.campus} onChange={(e) => set("campus", e.target.value)} />
              </Field>
              <div className="grid grid-cols-3 gap-3">
                <Field label="Major">
                  <Input value={draft.major} onChange={(e) => set("major", e.target.value)} />
                </Field>
                <Field label="Degree">
                  <Input value={draft.degree} onChange={(e) => set("degree", e.target.value)} />
                </Field>
                <Field label="Grad year">
                  <Input
                    type="number"
                    value={draft.graduation_year}
                    onChange={(e) => set("graduation_year", e.target.value)}
                  />
                </Field>
              </div>
            </div>
          </>
        )}

        {step === 1 && (
          <>
            <StepTitle
              title="What do you want to work on?"
              hint="Free-form. These drive the research agent and every match score."
            />
            <TagInput
              values={draft.interests.map((i) => ({ id: i, label: i }))}
              suggestions={SUGGESTED_INTERESTS}
              placeholder="e.g. LLM agents"
              onAdd={(label) => set("interests", [...draft.interests, label])}
              onRemove={(id) => set("interests", draft.interests.filter((i) => i !== id))}
            />
            <div className="mt-3 flex flex-wrap gap-1.5">
              {SUGGESTED_INTERESTS.filter((s) => !draft.interests.includes(s))
                .slice(0, 10)
                .map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => set("interests", [...draft.interests, s])}
                    className="rounded-[var(--radius-xs)] border border-[var(--border)] px-2 py-1 text-2xs text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
                  >
                    + {s}
                  </button>
                ))}
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <StepTitle
              title="What can you do?"
              hint="Uploading a resume adds more automatically. You can edit all of this later."
            />
            <TagInput
              values={draft.skills.map((s) => ({ id: s, label: s }))}
              suggestions={SUGGESTED_SKILLS}
              placeholder="e.g. Python"
              onAdd={(label) => set("skills", [...draft.skills, label])}
              onRemove={(id) => set("skills", draft.skills.filter((s) => s !== id))}
            />
          </>
        )}

        {step === 3 && (
          <>
            <StepTitle
              title="Upload your resumes"
              hint="Add more than one. Trellis picks the best fit per opportunity — it never rewrites them."
            />
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.txt,.md"
              multiple
              className="hidden"
              onChange={(e) => {
                const picked = Array.from(e.target.files ?? []).map((file) => ({
                  file,
                  label: file.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " "),
                }));
                setFiles((cur) => [...cur, ...picked]);
              }}
            />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              className="w-full rounded-[var(--radius-lg)] border border-dashed border-[var(--border-strong)] p-6 text-center hover:bg-[var(--bg-subtle)]"
            >
              <span className="text-sm font-medium">Choose files</span>
              <span className="mt-1 block text-xs text-[var(--text-tertiary)]">
                PDF, .txt or .md
              </span>
            </button>
            {files.length > 0 && (
              <ul className="mt-3 space-y-2">
                {files.map((f, i) => (
                  <li key={i} className="flex items-center gap-2">
                    <Input
                      value={f.label}
                      onChange={(e) =>
                        setFiles((cur) =>
                          cur.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)),
                        )
                      }
                      aria-label={`Label for ${f.file.name}`}
                    />
                    <span className="w-[140px] shrink-0 truncate text-2xs text-[var(--text-tertiary)]">
                      {f.file.name}
                    </span>
                    <Button
                      type="button"
                      variant="ghost"
                      size="xs"
                      onClick={() => setFiles((cur) => cur.filter((_, j) => j !== i))}
                    >
                      Remove
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-3 text-2xs text-[var(--text-tertiary)]">
              You can skip this and upload later.
            </p>
          </>
        )}

        {step === 4 && (
          <>
            <StepTitle title="What should we look for?" hint="You can change this any time." />
            <div className="space-y-2">
              {JOB_TYPES.map((t) => (
                <label
                  key={t.value}
                  className="flex cursor-pointer items-start gap-2.5 rounded-[var(--radius-md)] border border-[var(--border)] p-2.5 hover:bg-[var(--bg-subtle)]"
                >
                  <span className="pt-0.5">
                    <Checkbox
                      checked={draft.job_types.includes(t.value)}
                      onChange={(e) =>
                        set(
                          "job_types",
                          e.target.checked
                            ? [...draft.job_types, t.value]
                            : draft.job_types.filter((x) => x !== t.value),
                        )
                      }
                    />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-xs font-medium">{t.label}</span>
                    <span className="block text-2xs text-[var(--text-tertiary)]">{t.hint}</span>
                  </span>
                </label>
              ))}
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <Field label="Hours per week (min)">
                <Input
                  type="number"
                  value={draft.hours_min}
                  onChange={(e) => set("hours_min", e.target.value)}
                />
              </Field>
              <Field label="Hours per week (max)">
                <Input
                  type="number"
                  value={draft.hours_max}
                  onChange={(e) => set("hours_max", e.target.value)}
                />
              </Field>
            </div>
          </>
        )}

        {error && (
          <Alert tone="danger" className="mt-4">
            {error}
          </Alert>
        )}

        <div className="mt-6 flex items-center justify-between">
          <Tooltip content={step === 0 ? "This is the first step." : undefined}>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={step === 0}
              onClick={() => setStep((s) => Math.max(0, s - 1))}
            >
              Back
            </Button>
          </Tooltip>
          <div className="flex items-center gap-2">
            {step === 3 && files.length === 0 && (
              <Button type="button" variant="ghost" size="sm" onClick={next}>
                Skip
              </Button>
            )}
            <Button type="submit" variant="primary" disabled={!valid}>
              {step === STEPS.length - 1 ? "Start discovery" : "Continue"}
            </Button>
          </div>
        </div>
      </form>
    </Shell>
  );
}

function Shell({ step, children }: { step: number; children: React.ReactNode }) {
  return (
    <main className="mx-auto flex min-h-dvh max-w-[520px] flex-col justify-center px-5 py-10">
      <div className="mb-6 flex gap-1" aria-hidden>
        {STEPS.map((s, i) => (
          <span
            key={s}
            className={cn(
              "h-0.5 flex-1 rounded-full transition-colors",
              i <= step ? "bg-[var(--accent)]" : "bg-[var(--border)]",
            )}
          />
        ))}
      </div>
      {children}
    </main>
  );
}

function StepTitle({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="mb-5">
      <h1 className="text-xl font-semibold tracking-[-0.02em]">{title}</h1>
      <p className="mt-1 text-xs leading-relaxed text-[var(--text-tertiary)]">{hint}</p>
    </div>
  );
}
