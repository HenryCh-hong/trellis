import type { SearchRunSummary } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

/**
 * Quiet provenance line. Everything above it is only as fresh as this run, so
 * the page says when it happened and how much of the web it actually touched.
 */
export function LastRunLine({ run }: { run: SearchRunSummary | null }) {
  if (!run) {
    return (
      <p className="text-2xs text-[var(--text-tertiary)]">
        Discovery has not run yet — nothing on this page has been refreshed from a source.
        Use Run discovery above to fetch postings and lab pages.
      </p>
    );
  }

  if (run.status === "queued" || run.status === "running") {
    return (
      <p className="text-2xs text-[var(--text-tertiary)]">
        Discovery is running now across {run.sources_attempted.length} source
        {run.sources_attempted.length === 1 ? "" : "s"}. Refresh in a moment to see what it
        found.
      </p>
    );
  }

  const when = run.finished_at ?? run.started_at;
  const sources = run.sources_attempted.length;

  // What a run withheld is as much a part of its result as what it added, and
  // a line that only ever grows ("12 new") would quietly hide the filtering.
  // Zero buckets are dropped so the sentence stays short on a clean run.
  const withheld = [
    run.expired_count > 0 && `${run.expired_count} expired`,
    run.held_count > 0 && `${run.held_count} held as low-confidence`,
    run.skipped_count > 0 && `${run.skipped_count} not openings`,
    run.suppressed_count > 0 && `${run.suppressed_count} you had rejected`,
  ].filter((v): v is string => typeof v === "string");

  return (
    <p className="text-2xs leading-relaxed text-[var(--text-tertiary)]">
      Discovery last ran {formatDateTime(when)} · {sources} source{sources === 1 ? "" : "s"}{" "}
      touched · {run.documents_fetched} page{run.documents_fetched === 1 ? "" : "s"} read ·{" "}
      {run.created_count} new, {run.updated_count} updated, {run.unchanged_count} unchanged
      {withheld.length > 0 && ` · ${withheld.join(", ")}`}
      {run.status !== "succeeded" && (
        <span className="text-[var(--color-warn-700)]">
          {" "}
          · finished {run.status}
          {run.error ? `: ${run.error}` : ""}
        </span>
      )}
    </p>
  );
}
