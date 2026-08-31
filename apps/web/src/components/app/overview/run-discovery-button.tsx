"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { api, ApiError } from "@/lib/api";

/**
 * Runs both discovery kinds and reports what came back. Nothing is applied for
 * or emailed here — a run only fetches and scores.
 */
export function RunDiscoveryButton() {
  const router = useRouter();
  const { push } = useToast();
  const [running, setRunning] = React.useState(false);

  async function run() {
    setRunning(true);
    try {
      const runs = await Promise.all([
        api.searches.discover("jobs"),
        api.searches.discover("research"),
      ]);
      const created = runs.reduce((n, r) => n + r.created_count, 0);
      const updated = runs.reduce((n, r) => n + r.updated_count, 0);
      const failed = runs.find((r) => r.status === "failed");

      if (failed) {
        push(failed.error ?? "Discovery finished with errors.", "error");
      } else if (created > 0) {
        push(`${created} new ${created === 1 ? "opportunity" : "opportunities"} found.`, "success");
      } else {
        push(`No new postings · ${updated} updated.`);
      }
      router.refresh();
    } catch (error) {
      push(
        error instanceof ApiError ? error.message : "Discovery could not be started.",
        "error",
      );
    } finally {
      setRunning(false);
    }
  }

  return (
    <Button variant="secondary" size="sm" loading={running} onClick={run}>
      {running ? "Running…" : "Run discovery"}
    </Button>
  );
}
