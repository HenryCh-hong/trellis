"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

import { PageHeader } from "@/components/app/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Alert,
  Badge,
  Card,
  ExternalLink,
  SectionHeader,
  SegmentedControl,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import {
  FALLBACK_OFFSETS,
  parseOffsets,
  readDefaultOffsets,
  writeDefaultOffsets,
} from "@/lib/reminder-prefs";
import type { DataSourceInfo, ProvenanceInfo, ReminderProviderInfo } from "@/lib/types";
import { formatDateTime, hostOf } from "@/lib/utils";

type Theme = "light" | "dark";

export function SettingsClient({
  sources,
  provenance,
  providers,
}: {
  sources: DataSourceInfo[];
  provenance: ProvenanceInfo[];
  providers: ReminderProviderInfo[];
}) {
  const router = useRouter();
  const toast = useToast();
  // Read once during initialisation rather than setting state from an effect,
  // which triggers a second render pass on every mount.
  const [theme, setTheme] = React.useState<Theme>(() => {
    if (typeof window === "undefined") return "light";
    try {
      const stored = window.localStorage.getItem("trellis-theme");
      return stored === "dark" || stored === "light" ? stored : "light";
    } catch {
      return "light";
    }
  });
  const [offsets, setOffsets] = React.useState(() => {
    if (typeof window === "undefined") return FALLBACK_OFFSETS.join(", ");
    return readDefaultOffsets().join(", ");
  });
  const [offsetsSaved, setOffsetsSaved] = React.useState(false);
  const [confirmText, setConfirmText] = React.useState("");
  const [deleting, setDeleting] = React.useState(false);

  React.useEffect(() => {
    // Only the DOM side-effect belongs here; both pieces of state are read
    // during initialisation instead of being synced from an effect.
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  function applyTheme(next: Theme) {
    setTheme(next);
    document.documentElement.dataset.theme = next;
    try {
      window.localStorage.setItem("trellis-theme", next);
    } catch {
      // Not persisting is acceptable; the page still renders correctly.
    }
  }

  // Three honest buckets. A flat list mixed live adapters with pages that were
  // checked and yielded nothing, which made the whole thing read as noise —
  // but deleting the empty ones would throw away useful negative provenance.
  const feeding = sources.filter((s) => !s.requires_auth && s.opportunity_count > 0);
  const authSources = sources.filter((s) => s.requires_auth);
  const quiet = sources.filter((s) => !s.requires_auth && s.opportunity_count === 0);

  return (
    <>
      <PageHeader title="Settings" />
      <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[800px] space-y-5 p-5">
          <Card className="p-4">
            <SectionHeader
              title="Data sources"
              count={sources.length}
              description="Where opportunities come from, and which ones need your own login."
            />
            <SourceTable rows={feeding} />
            {authSources.length > 0 && (
              <>
                <h4 className="mb-1.5 mt-4 text-2xs uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
                  Needs your login
                </h4>
                <SourceTable rows={authSources} />
                <Alert tone="neutral" className="mt-2">
                  Trellis will not sign in to these for you or work around their login. Handshake
                  jobs are imported by the browser extension, reading only what you can already see
                  in your own logged-in tab.
                </Alert>
              </>
            )}

            {quiet.length > 0 && (
              <details className="mt-4">
                <summary className="cursor-pointer text-2xs uppercase tracking-[0.05em] text-[var(--text-tertiary)] hover:text-[var(--text-primary)]">
                  Checked, currently yielding nothing ({quiet.length})
                </summary>
                <p className="mb-2 mt-1.5 text-2xs leading-relaxed text-[var(--text-tertiary)]">
                  Kept on purpose. That a page was checked and had no student postings is a fact
                  worth knowing — it is why campus coverage is a floor rather than a census.
                </p>
                <SourceTable rows={quiet} />
              </details>
            )}
          </Card>

          <Card className="p-4">
            <SectionHeader
              title="Where this data came from"
              description="Including what could not be collected."
            />
            {provenance.length === 0 ? (
              <p className="text-xs text-[var(--text-tertiary)]">No provenance recorded.</p>
            ) : (
              provenance.map((p) => <ProvenanceBlock key={p.key} info={p} />)
            )}
          </Card>

          <Card className="p-4">
            <SectionHeader
              title="Deadline reminders"
              description="Defaults for new reminders. Each reminder keeps its own offsets."
            />
            <label className="flex max-w-[280px] flex-col gap-1.5">
              <span className="text-xs font-medium text-[var(--text-secondary)]">
                Remind me this many days before
              </span>
              <Input
                value={offsets}
                onChange={(e) => {
                  setOffsets(e.target.value);
                  setOffsetsSaved(false);
                }}
                onBlur={() => {
                  const parsed = parseOffsets(offsets);
                  if (!parsed.length) return;
                  setOffsetsSaved(writeDefaultOffsets(parsed));
                }}
                placeholder="7, 3, 1"
              />
              <span className="text-2xs text-[var(--text-tertiary)]">
                {offsetsSaved
                  ? "Saved. New reminders start with these offsets."
                  : "Seeds new reminders. Each reminder keeps its own offsets once created."}
              </span>
            </label>
            <div className="mt-3 space-y-2">
              {providers.map((p) => (
                <div key={p.slug} className="flex items-start gap-2.5">
                  <Badge tone={p.slug === "ics" ? "accent" : "neutral"}>{p.label}</Badge>
                  <p className="text-xs leading-relaxed text-[var(--text-tertiary)]">
                    {p.description}
                  </p>
                </div>
              ))}
            </div>
          </Card>

          <Card className="p-4">
            <SectionHeader title="Appearance" />
            <SegmentedControl
              options={[
                { value: "light", label: "Light" },
                { value: "dark", label: "Dark" },
              ]}
              value={theme}
              onChange={(v) => applyTheme(v as Theme)}
            />
          </Card>

          <Card className="p-4">
            <SectionHeader title="Privacy & data" />
            <ul className="space-y-1.5 text-xs leading-relaxed text-[var(--text-secondary)]">
              <li>· No third-party password is ever stored. Trellis has no Handshake credentials.</li>
              <li>
                · Resumes are kept outside any web-served directory and are only reachable through
                an authorised API route.
              </li>
              <li>· Application answers are never written to logs.</li>
              <li>· Nothing is submitted anywhere without your explicit, per-payload approval.</li>
              <li>
                · Sensitive questions (work authorisation, demographics, disability, veteran status)
                are never auto-filled or drafted.
              </li>
            </ul>

            <div className="mt-4 rounded-[var(--radius-md)] border border-[var(--color-danger-200)] bg-[var(--color-danger-50)] p-3">
              <h4 className="text-xs font-medium text-[var(--color-danger-700)]">
                Delete all my data
              </h4>
              <p className="mt-1 text-2xs leading-relaxed text-[var(--color-danger-700)]">
                Removes your profile, resumes (including the files on disk), applications and
                reminders. The public research corpus is not personal data and stays.
              </p>
              <div className="mt-2.5 flex items-center gap-2">
                <Input
                  value={confirmText}
                  onChange={(e) => setConfirmText(e.target.value)}
                  placeholder="Type DELETE to confirm"
                  className="max-w-[220px]"
                  aria-label="Type DELETE to confirm"
                />
                <Button
                  variant="danger"
                  disabled={confirmText !== "DELETE" || deleting}
                  loading={deleting}
                  onClick={async () => {
                    setDeleting(true);
                    try {
                      await api.settings.deleteAccount();
                      toast.push("Your data has been deleted", "success");
                      router.push("/onboarding");
                    } catch (error) {
                      toast.push(
                        error instanceof Error ? error.message : "Could not delete",
                        "error",
                      );
                    } finally {
                      setDeleting(false);
                    }
                  }}
                >
                  Delete everything
                </Button>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}

function SourceTable({ rows }: { rows: DataSourceInfo[] }) {
  if (rows.length === 0) {
    return <p className="text-xs text-[var(--text-tertiary)]">None.</p>;
  }
  return (
    <div className="overflow-hidden rounded-[var(--radius-md)] border border-[var(--border-subtle)]">
      <table className="w-full text-left">
        <thead className="bg-[var(--bg-subtle)]">
          <tr className="text-2xs uppercase tracking-[0.04em] text-[var(--text-tertiary)]">
            <th className="px-3 py-1.5 font-medium">Source</th>
            <th className="hidden px-3 py-1.5 font-medium sm:table-cell">Kind</th>
            <th className="px-3 py-1.5 font-medium">Items</th>
            <th className="hidden px-3 py-1.5 font-medium md:table-cell">Last run</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--border-subtle)]">
          {rows.map((s) => (
            <tr key={s.slug}>
              <td className="px-3 py-2">
                <div className="text-xs font-medium">{s.name}</div>
                {s.base_url && (
                  <ExternalLink href={s.base_url} className="text-2xs">
                    {hostOf(s.base_url)}
                  </ExternalLink>
                )}
                {s.notes && (
                  <p className="mt-0.5 max-w-[420px] text-2xs leading-relaxed text-[var(--text-tertiary)]">
                    {s.notes}
                  </p>
                )}
              </td>
              <td className="hidden px-3 py-2 text-2xs text-[var(--text-tertiary)] sm:table-cell">
                {s.kind.replace(/_/g, " ")}
              </td>
              <td className="px-3 py-2 text-xs tabular-nums">{s.opportunity_count}</td>
              <td className="hidden whitespace-nowrap px-3 py-2 text-2xs text-[var(--text-tertiary)] md:table-cell">
                {s.last_run_at ? formatDateTime(s.last_run_at) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ProvenanceBlock({ info }: { info: ProvenanceInfo }) {
  const detail = info.detail as {
    counts?: Record<string, number>;
    known_gaps?: string[];
    university?: string;
  };
  const [expanded, setExpanded] = React.useState(false);
  const gaps = detail.known_gaps ?? [];
  const shown = expanded ? gaps : gaps.slice(0, 4);

  return (
    <div className="mb-4 last:mb-0">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-xs font-medium">{info.label}</span>
        {info.generated_at && (
          <span className="text-2xs text-[var(--text-tertiary)]">
            collected {formatDateTime(info.generated_at)}
          </span>
        )}
      </div>

      {detail.counts && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {Object.entries(detail.counts).map(([k, v]) => (
            <Badge key={k} tone="neutral">
              {v} {k.replace(/_/g, " ")}
            </Badge>
          ))}
        </div>
      )}

      {gaps.length > 0 && (
        <div className="mt-3">
          <h4 className="text-2xs uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
            Known gaps ({gaps.length})
          </h4>
          <ul className="mt-1.5 space-y-1.5">
            {shown.map((g, i) => (
              <li key={i} className="text-2xs leading-relaxed text-[var(--text-secondary)]">
                · {g}
              </li>
            ))}
          </ul>
          {gaps.length > 4 && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="mt-1.5 text-2xs text-[var(--accent)] hover:underline"
            >
              {expanded ? "Show fewer" : `Show all ${gaps.length}`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
