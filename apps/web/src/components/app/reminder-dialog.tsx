"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PanelSection, SidePanel } from "@/components/ui/panel";
import { Alert, Badge } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { API_BASE, api } from "@/lib/api";
import type { OpportunityListItem, ReminderItem } from "@/lib/types";
import { FALLBACK_OFFSETS, parseOffsets, readDefaultOffsets } from "@/lib/reminder-prefs";
import { formatDate } from "@/lib/utils";

/**
 * Reminders, end to end.
 *
 * Creating a row and stopping there would be a dead end: the student could
 * "add a reminder" and never be reminded of anything. So this panel does the
 * whole job — pick the offsets, create it, and get it out of Trellis and into
 * something that will actually alert you.
 *
 * Trellis cannot write into Apple Reminders directly; no local web app can
 * without the user granting an automation access. Rather than pretend, the
 * Apple path is presented as what it is: a one-time Shortcut you install, then
 * a payload we hand it. The .ics path needs no setup at all and is the default.
 */
export function ReminderDialog({
  open,
  onClose,
  opportunity,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  opportunity: OpportunityListItem;
  onCreated?: (r: ReminderItem) => void;
}) {
  const toast = useToast();
  const [offsets, setOffsets] = React.useState(() =>
    typeof window === "undefined"
      ? FALLBACK_OFFSETS.join(", ")
      : readDefaultOffsets().join(", "),
  );
  const [reminder, setReminder] = React.useState<ReminderItem | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [apple, setApple] = React.useState<{
    available: boolean;
    reason: string;
    needs_permission: boolean;
  } | null>(null);
  const [appleResult, setAppleResult] = React.useState<string | null>(null);
  const [shortcut, setShortcut] = React.useState<{
    payload: unknown;
    instructions: string;
    shortcut_recipe: string[];
  } | null>(null);

  // An existing reminder for this opportunity should be reused, not duplicated.
  // The parent mounts this only while open, so this runs once per opening and
  // does not have to reset state that was left behind.
  React.useEffect(() => {
    if (!open) return;
    let cancelled = false;
    api.reminders
      .list()
      .then((all) => {
        if (cancelled) return;
        const mine = all.find((r) => r.opportunity_id === opportunity.id);
        if (mine) {
          setReminder(mine);
          setOffsets(mine.offsets_days.join(", "));
        }
      })
      .catch(() => undefined);
    // Ask before offering the button: an integration that cannot run should say
    // why rather than fail when pressed.
    api.reminders
      .appleAvailability()
      .then((a) => !cancelled && setApple(a))
      .catch(() => !cancelled && setApple({ available: false, reason: "Could not reach the Trellis API.", needs_permission: false }));

    return () => {
      cancelled = true;
    };
  }, [open, opportunity.id]);

  async function sendToApple(id: string) {
    setBusy(true);
    try {
      const res = await api.reminders.sendToApple(id);
      setAppleResult(res.note);
      toast.push(res.note, "success");
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "Could not add them", "error");
    } finally {
      setBusy(false);
    }
  }

  const parsedOffsets = React.useMemo(() => parseOffsets(offsets), [offsets]);

  async function create() {
    setBusy(true);
    try {
      const created = await api.reminders.create({
        opportunity_id: opportunity.id,
        provider: "ics",
        offsets_days: parsedOffsets.length ? parsedOffsets : undefined,
      });
      setReminder(created);
      onCreated?.(created);
      toast.push("Reminder created", "success");
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "Could not create it", "error");
    } finally {
      setBusy(false);
    }
  }

  async function loadShortcut(id: string) {
    setBusy(true);
    try {
      const data = (await api.reminders.shortcut(id)) as unknown as {
        payload: unknown;
        instructions: string;
        shortcut_recipe: string[];
      };
      setShortcut(data);
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "Could not load it", "error");
    } finally {
      setBusy(false);
    }
  }

  const noDeadline = !opportunity.deadline;

  return (
    <SidePanel
      open={open}
      onClose={onClose}
      width="narrow"
      title={<h2 className="text-sm font-semibold">Remind me about this</h2>}
      subtitle={
        <p className="mt-0.5 truncate text-xs text-[var(--text-tertiary)]">
          {opportunity.title}
        </p>
      }
    >
      {noDeadline ? (
        <PanelSection>
          <Alert tone="neutral" title="No deadline was found">
            Nothing on the source page stated a date, so there is nothing to count down to. If
            you know the deadline, open the posting and add it to your own calendar.
          </Alert>
        </PanelSection>
      ) : (
        <>
          <PanelSection title="Deadline">
            <div className="flex items-baseline gap-2">
              <span className="text-sm font-medium tnum">{formatDate(opportunity.deadline, { year: true })}</span>
              <Badge tone={opportunity.deadline_certainty === "verified" ? "success" : "warn"}>
                {opportunity.deadline_certainty}
              </Badge>
            </div>
          </PanelSection>

          <PanelSection title="Alert me">
            <label className="block">
              <span className="mb-1 block text-xs text-[var(--text-secondary)]">
                Days before the deadline
              </span>
              <Input
                value={offsets}
                onChange={(e) => setOffsets(e.target.value)}
                disabled={reminder !== null}
                aria-label="Days before the deadline"
                className="max-w-[200px]"
              />
            </label>
            <p className="mt-1.5 text-2xs text-[var(--text-tertiary)]">
              {parsedOffsets.length
                ? `${parsedOffsets.length} alert(s): ${parsedOffsets.map((d) => `${d}d before`).join(", ")}`
                : "Enter one or more numbers, e.g. 7, 3, 1"}
            </p>

            {!reminder && (
              <Button
                variant="primary"
                size="sm"
                className="mt-3"
                loading={busy}
                disabled={parsedOffsets.length === 0}
                onClick={() => void create()}
              >
                Create reminder
              </Button>
            )}
          </PanelSection>

          {reminder && (
            <>
              <PanelSection title="Apple Reminders">
                {apple === null ? (
                  <p className="text-xs text-[var(--text-tertiary)]">Checking…</p>
                ) : apple.available ? (
                  <>
                    <p className="mb-2 text-xs leading-relaxed text-[var(--text-secondary)]">
                      Adds {reminder.offsets_days.length} reminder
                      {reminder.offsets_days.length === 1 ? "" : "s"} to a “Trellis” list in the
                      Reminders app on this Mac — one per alert. They sync to your iPhone through
                      iCloud.
                    </p>
                    {appleResult ? (
                      <Alert tone="success">{appleResult}</Alert>
                    ) : (
                      <Button
                        variant="primary"
                        size="sm"
                        loading={busy}
                        onClick={() => void sendToApple(reminder.id)}
                      >
                        Add to Apple Reminders
                      </Button>
                    )}
                  </>
                ) : (
                  <Alert tone="neutral" title="Not available here">
                    {apple.reason}
                    {apple.needs_permission && (
                      <span className="mt-1 block">
                        Approve Trellis under System Settings → Privacy &amp; Security → Reminders,
                        then try again.
                      </span>
                    )}
                  </Alert>
                )}
              </PanelSection>

              <PanelSection title="Add it to your calendar">
                <p className="mb-2 text-xs leading-relaxed text-[var(--text-secondary)]">
                  Downloads a calendar file with {reminder.offsets_days.length} alert
                  {reminder.offsets_days.length === 1 ? "" : "s"}. Works with Apple Calendar,
                  Google Calendar and Outlook. Nothing leaves your machine.
                </p>
                {/* A real download link, not a navigation: the browser saves
                    the file and the page stays where it is. */}
                <a
                  href={`${API_BASE}/api/reminders/${reminder.id}/export.ics`}
                  download
                  className="inline-flex h-7 items-center justify-center gap-1.5 rounded-[var(--radius-sm)] bg-[var(--accent)] px-2.5 text-xs font-medium text-white shadow-xs transition-colors hover:bg-[var(--accent-hover)]"
                >
                  Download .ics
                </a>
              </PanelSection>

              <PanelSection title="Apple Shortcut (for another device)">
                <Alert tone="neutral" className="mb-2">
                  Only needed if you want these on a machine that is not running Trellis. On this
                  Mac, use the button above.
                </Alert>
                {!shortcut ? (
                  <Button
                    variant="secondary"
                    size="sm"
                    loading={busy}
                    onClick={() => void loadShortcut(reminder.id)}
                  >
                    Show the setup
                  </Button>
                ) : (
                  <>
                    <ol className="space-y-1.5">
                      {shortcut.shortcut_recipe.map((step, i) => (
                        <li
                          key={i}
                          className="flex gap-2 text-2xs leading-relaxed text-[var(--text-secondary)]"
                        >
                          <span className="tabular-nums text-[var(--text-tertiary)]">{i + 1}.</span>
                          {step}
                        </li>
                      ))}
                    </ol>
                    <div className="mt-3">
                      <div className="mb-1 text-2xs uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
                        Payload
                      </div>
                      <pre className="scrollbar-thin max-h-40 overflow-auto rounded-[var(--radius-sm)] bg-[var(--bg-sunken)] p-2 font-mono text-[10px] leading-relaxed">
                        {JSON.stringify(shortcut.payload, null, 2)}
                      </pre>
                      <Button
                        variant="secondary"
                        size="sm"
                        className="mt-2"
                        onClick={async () => {
                          try {
                            await navigator.clipboard.writeText(
                              JSON.stringify(shortcut.payload, null, 2),
                            );
                            toast.push("Payload copied", "success");
                          } catch {
                            toast.push("Your browser blocked the clipboard", "error");
                          }
                        }}
                      >
                        Copy payload
                      </Button>
                    </div>
                  </>
                )}
              </PanelSection>
            </>
          )}
        </>
      )}
    </SidePanel>
  );
}
