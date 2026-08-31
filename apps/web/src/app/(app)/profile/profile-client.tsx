"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

import { PageHeader } from "@/components/app/page-header";
import { SUGGESTED_INTERESTS, SUGGESTED_SKILLS, TagInput } from "@/components/app/tag-input";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Switch } from "@/components/ui/input";
import { Alert, Badge, Card, SectionHeader, Tooltip } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import type { StudentProfile } from "@/lib/types";
import { formatDate } from "@/lib/utils";

const WORK_AUTH = [
  { value: "not_specified", label: "Prefer not to say" },
  { value: "us_citizen_or_pr", label: "U.S. citizen or permanent resident" },
  { value: "f1_cpt_opt", label: "F-1 student (CPT/OPT)" },
  { value: "other_visa", label: "Other visa status" },
];

const JOB_TYPES = [
  { value: "on_campus", label: "On-campus jobs" },
  { value: "part_time", label: "Part-time jobs" },
  { value: "research_opening", label: "Research openings" },
  { value: "research_outreach", label: "Lab outreach" },
];

export function ProfileClient({ initial }: { initial: StudentProfile }) {
  const router = useRouter();
  const toast = useToast();
  const [profile, setProfile] = React.useState(initial);
  const [saved, setSaved] = React.useState<string | null>(null);

  const flash = React.useCallback(() => {
    setSaved("Saved");
    setTimeout(() => setSaved(null), 1600);
  }, []);

  async function save(patch: Partial<StudentProfile>) {
    try {
      setProfile(await api.profile.update(patch));
      flash();
      router.refresh();
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "That did not save", "error");
    }
  }

  /** Autosave on blur — only when the value actually changed. */
  function onBlurSave<K extends keyof StudentProfile>(key: K, parse?: (v: string) => unknown) {
    return (e: React.FocusEvent<HTMLInputElement | HTMLSelectElement>) => {
      const raw = e.target.value;
      const value = parse ? parse(raw) : raw || null;
      if (value === profile[key]) return;
      save({ [key]: value } as Partial<StudentProfile>);
    };
  }

  const num = (v: string) => (v.trim() === "" ? null : Number(v));

  return (
    <>
      <PageHeader
        title="Profile"
        description="Used to rank opportunities and check eligibility. Nothing here is submitted anywhere without your review."
        actions={
          saved && (
            <span className="animate-fade-in text-xs text-[var(--color-success-700)]">{saved}</span>
          )
        }
      />

      <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[760px] space-y-5 p-5">
          <Card className="p-4">
            <SectionHeader title="Academic" />
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="University">
                <Input defaultValue={profile.university} onBlur={onBlurSave("university")} />
              </Field>
              <Field label="Campus">
                <Input defaultValue={profile.campus ?? ""} onBlur={onBlurSave("campus")} />
              </Field>
              <Field label="Major">
                <Input defaultValue={profile.major ?? ""} onBlur={onBlurSave("major")} />
              </Field>
              <Field label="Second major or minor">
                <Input
                  defaultValue={profile.secondary_major ?? ""}
                  onBlur={onBlurSave("secondary_major")}
                />
              </Field>
              <Field label="Degree">
                <Input
                  defaultValue={profile.degree ?? ""}
                  placeholder="BS"
                  onBlur={onBlurSave("degree")}
                />
              </Field>
              <Field label="Expected graduation">
                <Input
                  type="number"
                  defaultValue={profile.graduation_year ?? ""}
                  onBlur={onBlurSave("graduation_year", num)}
                />
              </Field>
              <Field label="GPA" hint="Optional. Only used if you switch it on below.">
                <Input
                  type="number"
                  step="0.01"
                  defaultValue={profile.gpa ?? ""}
                  onBlur={onBlurSave("gpa", num)}
                />
              </Field>
              <div className="flex items-end pb-1">
                <label className="flex items-center gap-2">
                  <Switch
                    checked={profile.gpa_is_public}
                    onCheckedChange={(v) => save({ gpa_is_public: v })}
                    label="Use my GPA in applications"
                  />
                  <span className="text-xs text-[var(--text-secondary)]">
                    Use my GPA in applications
                  </span>
                </label>
              </div>
            </div>
          </Card>

          <Card className="p-4">
            <SectionHeader title="Availability" />
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Hours per week (min)">
                <Input
                  type="number"
                  defaultValue={profile.hours_per_week_min ?? ""}
                  onBlur={onBlurSave("hours_per_week_min", num)}
                />
              </Field>
              <Field label="Hours per week (max)">
                <Input
                  type="number"
                  defaultValue={profile.hours_per_week_max ?? ""}
                  onBlur={onBlurSave("hours_per_week_max", num)}
                />
              </Field>
            </div>
            <div className="mt-3">
              <span className="text-xs font-medium text-[var(--text-secondary)]">
                What to search for
              </span>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {JOB_TYPES.map((t) => {
                  const on = profile.preferred_job_types.includes(t.value);
                  return (
                    <button
                      key={t.value}
                      onClick={() =>
                        save({
                          preferred_job_types: on
                            ? profile.preferred_job_types.filter((x) => x !== t.value)
                            : [...profile.preferred_job_types, t.value],
                        })
                      }
                      className={
                        on
                          ? "rounded-[var(--radius-xs)] border border-[var(--accent-border)] bg-[var(--accent-soft)] px-2 py-1 text-2xs font-medium text-[var(--color-accent-700)]"
                          : "rounded-[var(--radius-xs)] border border-[var(--border)] px-2 py-1 text-2xs text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
                      }
                    >
                      {t.label}
                    </button>
                  );
                })}
              </div>
            </div>
          </Card>

          <Card className="p-4">
            <SectionHeader title="Work authorisation" />
            <Alert tone="neutral" className="mb-3">
              Used only to check whether you appear eligible for a role. Trellis never answers a
              work-authorisation question on an application for you.
            </Alert>
            <Field label="Status">
              <Select
                aria-label="Work authorisation status"
                defaultValue={profile.work_authorization}
                onChange={(e) => save({ work_authorization: e.target.value })}
              >
                {WORK_AUTH.map((w) => (
                  <option key={w.value} value={w.value}>
                    {w.label}
                  </option>
                ))}
              </Select>
            </Field>
          </Card>

          <Card className="p-4">
            <SectionHeader
              title="Research interests"
              description="What the research agent searches for, and what lab matches are scored against."
            />
            <TagInput
              values={profile.interests.map((i) => ({ id: i.id, label: i.label }))}
              suggestions={SUGGESTED_INTERESTS}
              placeholder="e.g. LLM agents, AI + education"
              ariaLabel="Add a research interest"
              addMoreLabel="Add another interest…"
              onAdd={async (label) => {
                setProfile(await api.profile.addInterest(label));
                flash();
                router.refresh();
              }}
              onRemove={async (id) => {
                setProfile(await api.profile.removeInterest(id));
                flash();
                router.refresh();
              }}
            />
          </Card>

          <Card className="p-4">
            <SectionHeader title="Skills" />
            <TagInput
              values={profile.skills.map((s) => ({
                id: s.id,
                label: s.label,
                hint: s.origin === "resume" ? "from resume" : undefined,
              }))}
              suggestions={SUGGESTED_SKILLS}
              placeholder="e.g. Python, PyTorch"
              ariaLabel="Add a skill"
              addMoreLabel="Add another skill…"
              onAdd={async (label) => {
                setProfile(await api.profile.addSkill(label));
                flash();
              }}
              onRemove={async (id) => {
                setProfile(await api.profile.removeSkill(id));
                flash();
              }}
            />
            <p className="mt-2 text-2xs text-[var(--text-tertiary)]">
              Skills marked “from resume” were found in a file you uploaded. Nothing is added
              unless you typed it or it appears in your own resume.
            </p>
          </Card>

          <Card className="p-4">
            <SectionHeader title="Coursework" count={profile.coursework.length} />
            <CourseForm
              onAdd={async (payload) => {
                setProfile(await api.profile.addCourse(payload));
                flash();
              }}
            />
            {profile.coursework.length > 0 && (
              <ul className="mt-3 divide-y divide-[var(--border-subtle)]">
                {profile.coursework.map((c) => (
                  <li key={c.id} className="flex items-center gap-3 py-1.5">
                    {c.code && (
                      <span className="w-[76px] shrink-0 font-mono text-2xs text-[var(--text-tertiary)]">
                        {c.code}
                      </span>
                    )}
                    <span className="min-w-0 flex-1 truncate text-xs">{c.title}</span>
                    {c.term && (
                      <span className="text-2xs text-[var(--text-tertiary)]">{c.term}</span>
                    )}
                    <Button
                      variant="ghost"
                      size="xs"
                      onClick={async () => {
                        setProfile(await api.profile.removeCourse(c.id));
                        flash();
                      }}
                    >
                      Remove
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card className="p-4">
            <SectionHeader
              title="Experience"
              count={profile.experiences.length}
              description="Read from your uploaded resumes. Trellis does not invent entries."
            />
            {profile.experiences.length === 0 ? (
              <p className="text-xs text-[var(--text-tertiary)]">
                Nothing parsed yet. Upload a resume and anything clearly stated will appear here.
              </p>
            ) : (
              <ul className="divide-y divide-[var(--border-subtle)]">
                {profile.experiences.map((x) => (
                  <li key={x.id} className="py-2">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="text-xs font-medium">
                        {x.role} · {x.organization}
                      </span>
                      <span className="shrink-0 text-2xs text-[var(--text-tertiary)]">
                        {[formatDate(x.started_on), formatDate(x.ended_on)]
                          .filter((d) => d !== "—")
                          .join(" – ")}
                      </span>
                    </div>
                    {x.origin === "resume" && (
                      <Badge tone="neutral" className="mt-1">
                        from resume
                      </Badge>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}

function CourseForm({
  onAdd,
}: {
  onAdd: (payload: { code?: string; title: string; term?: string }) => Promise<void>;
}) {
  const [code, setCode] = React.useState("");
  const [title, setTitle] = React.useState("");
  const [term, setTerm] = React.useState("");

  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!title.trim()) return;
        await onAdd({ code: code.trim() || undefined, title: title.trim(), term: term.trim() || undefined });
        setCode("");
        setTitle("");
        setTerm("");
      }}
    >
      <Input
        value={code}
        onChange={(e) => setCode(e.target.value)}
        placeholder="CS 221"
        className="w-[92px]"
        aria-label="Course code"
      />
      <Input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Artificial Intelligence"
        className="min-w-[180px] flex-1"
        aria-label="Course title"
      />
      <Input
        value={term}
        onChange={(e) => setTerm(e.target.value)}
        placeholder="Aut 2026"
        className="w-[96px]"
        aria-label="Term"
      />
      <Tooltip content={title.trim() ? undefined : "Give the course a title first."}>
        <Button type="submit" size="md" disabled={!title.trim()}>
          Add
        </Button>
      </Tooltip>
    </form>
  );
}
