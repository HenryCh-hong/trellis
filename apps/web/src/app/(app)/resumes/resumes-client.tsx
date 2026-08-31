"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

import { PageHeader } from "@/components/app/page-header";
import { Button } from "@/components/ui/button";
import { PanelSection, SidePanel } from "@/components/ui/panel";
import {
  Alert,
  Badge,
  EmptyState,
  ExternalLink,
  Skeleton,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import type { ResumeDetail, ResumeItem } from "@/lib/types";
import { cn, formatBytes, formatDate } from "@/lib/utils";

const ACCEPT = ".pdf,.txt,.md";

export function ResumesClient({ initial }: { initial: ResumeItem[] }) {
  const router = useRouter();
  const toast = useToast();
  const [resumes, setResumes] = React.useState(initial);
  const [dragging, setDragging] = React.useState(false);
  const [uploading, setUploading] = React.useState(false);
  const [openId, setOpenId] = React.useState<string | null>(null);
  const [detail, setDetail] = React.useState<ResumeDetail | null>(null);
  // Derived, not synced: a closed panel has no detail, so there is nothing to
  // clear in an effect.
  const shownDetail = openId ? detail : null;
  const [confirmDelete, setConfirmDelete] = React.useState<string | null>(null);
  const fileRef = React.useRef<HTMLInputElement>(null);

  async function upload(files: FileList | File[]) {
    setUploading(true);
    for (const file of Array.from(files)) {
      const label = file.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ");
      try {
        const created = await api.resumes.upload(file, label);
        setResumes((cur) => [created, ...cur]);
        toast.push(
          created.parse_status === "parsed"
            ? `${created.label} uploaded and parsed`
            : `${created.label} uploaded, but could not be parsed`,
          created.parse_status === "parsed" ? "success" : "error",
        );
      } catch (error) {
        toast.push(error instanceof Error ? error.message : "Upload failed", "error");
      }
    }
    setUploading(false);
    router.refresh();
  }

  React.useEffect(() => {
    if (!openId) return;
    let cancelled = false;
    api.resumes
      .get(openId)
      .then((d) => !cancelled && setDetail(d))
      .catch(() => !cancelled && setDetail(null));
    return () => {
      cancelled = true;
    };
  }, [openId]);

  return (
    <>
      <PageHeader
        title="Resumes"
        description="Trellis never rewrites a resume. It recommends which of yours to use for each opportunity."
        actions={
          <Button
            variant="primary"
            size="sm"
            onClick={() => fileRef.current?.click()}
            loading={uploading}
          >
            Upload
          </Button>
        }
      />

      <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto p-5">
        <input
          ref={fileRef}
          type="file"
          accept={ACCEPT}
          multiple
          className="hidden"
          onChange={(e) => e.target.files && upload(e.target.files)}
        />

        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            if (e.dataTransfer.files.length) upload(e.dataTransfer.files);
          }}
          onClick={() => fileRef.current?.click()}
          className={cn(
            "cursor-pointer rounded-[var(--radius-lg)] border border-dashed p-6 text-center transition-colors",
            dragging
              ? "border-[var(--accent)] bg-[var(--accent-soft)]"
              : "border-[var(--border-strong)] hover:bg-[var(--bg-subtle)]",
          )}
        >
          <p className="text-sm font-medium">Drop a resume here, or click to choose</p>
          <p className="mt-1 text-xs text-[var(--text-tertiary)]">
            PDF, .txt or .md up to 10MB. Upload several — a research resume and a campus-jobs
            resume get matched to different opportunities.
          </p>
        </div>

        {resumes.length === 0 ? (
          <EmptyState
            className="py-16"
            title="No resumes yet"
            body="Upload at least one. Trellis reads it to match you against opportunities, and quotes your own lines back to you — it never adds experience you don't have."
          />
        ) : (
          <div className="mt-5 overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border)]">
            <table className="w-full text-left">
              <thead className="bg-[var(--bg-subtle)]">
                <tr className="text-2xs uppercase tracking-[0.04em] text-[var(--text-tertiary)]">
                  <th className="px-3 py-2 font-medium">Label</th>
                  <th className="hidden px-3 py-2 font-medium sm:table-cell">File</th>
                  <th className="hidden px-3 py-2 font-medium md:table-cell">Size</th>
                  <th className="px-3 py-2 font-medium">Parsed</th>
                  <th className="px-3 py-2 font-medium">Default</th>
                  <th className="hidden px-3 py-2 font-medium lg:table-cell">Uploaded</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border-subtle)]">
                {resumes.map((r) => (
                  <tr
                    key={r.id}
                    onClick={() => setOpenId(r.id)}
                    className="cursor-pointer hover:bg-[var(--bg-hover)]"
                  >
                    <td className="px-3 py-2.5 text-xs font-medium">{r.label}</td>
                    <td className="hidden max-w-[200px] truncate px-3 py-2.5 text-xs text-[var(--text-tertiary)] sm:table-cell">
                      {r.original_filename}
                    </td>
                    <td className="hidden px-3 py-2.5 text-xs tabular-nums text-[var(--text-tertiary)] md:table-cell">
                      {formatBytes(r.size_bytes)}
                    </td>
                    <td className="px-3 py-2.5">
                      {r.parse_status === "parsed" ? (
                        <Badge tone="success">{r.highlight_count} lines</Badge>
                      ) : (
                        <Badge tone="danger">Failed</Badge>
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      <input
                        type="radio"
                        name="default-resume"
                        checked={r.is_default}
                        onClick={(e) => e.stopPropagation()}
                        onChange={async () => {
                          await api.resumes.setDefault(r.id);
                          setResumes((cur) =>
                            cur.map((x) => ({ ...x, is_default: x.id === r.id })),
                          );
                        }}
                        className="accent-[var(--accent)]"
                        aria-label={`Use ${r.label} by default`}
                      />
                    </td>
                    <td className="hidden whitespace-nowrap px-3 py-2.5 text-2xs text-[var(--text-tertiary)] lg:table-cell">
                      {formatDate(r.created_at)}
                    </td>
                    <td className="px-3 py-2.5 text-right" onClick={(e) => e.stopPropagation()}>
                      {confirmDelete === r.id ? (
                        <span className="flex items-center justify-end gap-1.5">
                          <Button
                            variant="danger"
                            size="xs"
                            onClick={async () => {
                              await api.resumes.remove(r.id);
                              setResumes((cur) => cur.filter((x) => x.id !== r.id));
                              setConfirmDelete(null);
                              toast.push("Resume deleted", "success");
                              router.refresh();
                            }}
                          >
                            Delete
                          </Button>
                          <Button variant="ghost" size="xs" onClick={() => setConfirmDelete(null)}>
                            Cancel
                          </Button>
                        </span>
                      ) : (
                        <Button variant="ghost" size="xs" onClick={() => setConfirmDelete(r.id)}>
                          Delete
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <SidePanel
        open={openId !== null}
        onClose={() => setOpenId(null)}
        title={<h2 className="text-sm font-semibold">{detail?.label ?? "Resume"}</h2>}
        subtitle={
          shownDetail && (
            <p className="mt-0.5 text-xs text-[var(--text-tertiary)]">
              {shownDetail.original_filename} · {formatBytes(shownDetail.size_bytes)}
              {shownDetail.page_count ? ` · ${shownDetail.page_count} pages` : ""}
            </p>
          )
        }
        actions={
          shownDetail && (
            <ExternalLink href={api.resumes.fileUrl(shownDetail.id)} className="text-xs">
              Original
            </ExternalLink>
          )
        }
      >
        {!shownDetail ? (
          <PanelSection>
            <Skeleton className="h-24 w-full" />
          </PanelSection>
        ) : shownDetail.parse_status !== "parsed" ? (
          <PanelSection>
            <Alert tone="danger" title="This file could not be parsed">
              {shownDetail.parse_error ??
                "No text could be extracted. If it is a scan, export a text-based PDF instead."}
            </Alert>
          </PanelSection>
        ) : (
          <>
            <PanelSection title="Detected skills">
              {shownDetail.detected_skills.length === 0 ? (
                <p className="text-xs text-[var(--text-tertiary)]">
                  No skills from our vocabulary appeared in this file.
                </p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {shownDetail.detected_skills.map((s) => (
                    <Badge key={s} tone="neutral">
                      {s}
                    </Badge>
                  ))}
                </div>
              )}
            </PanelSection>

            {shownDetail.detected_topics.length > 0 && (
              <PanelSection title="Research topics">
                <div className="flex flex-wrap gap-1.5">
                  {shownDetail.detected_topics.map((t) => (
                    <Badge key={t} tone="accent">
                      {t}
                    </Badge>
                  ))}
                </div>
              </PanelSection>
            )}

            <PanelSection
              title={`Lines Trellis can quote (${shownDetail.highlights.length})`}
            >
              <p className="mb-2 text-2xs text-[var(--text-tertiary)]">
                Kept verbatim. Anything shown as “worth leading with” comes from this list.
              </p>
              <ul className="space-y-1.5">
                {shownDetail.highlights.map((h) => (
                  <li
                    key={h.id}
                    className="rounded-[var(--radius-xs)] bg-[var(--bg-sunken)] px-2 py-1.5 font-mono text-2xs leading-relaxed"
                  >
                    {h.text}
                  </li>
                ))}
              </ul>
            </PanelSection>
          </>
        )}
      </SidePanel>
    </>
  );
}
