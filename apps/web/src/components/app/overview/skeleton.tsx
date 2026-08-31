import { Card, Skeleton } from "@/components/ui/primitives";
import { OverviewBody } from "./shell";

/**
 * Placeholder that occupies the same boxes as the real page, so the content
 * lands in place instead of pushing the layout around when it arrives.
 */
export function OverviewSkeleton() {
  return (
    <>
      <div className="sticky top-0 z-20 border-b border-[var(--border)] bg-[var(--bg)]/85 backdrop-blur-sm">
        <div className="flex min-h-12 items-center gap-4 px-5 py-2.5">
          <div className="min-w-0 flex-1">
            <Skeleton className="h-3.5 w-24" />
            <Skeleton className="mt-1.5 h-2.5 w-44" />
          </div>
          <Skeleton className="h-7 w-[108px] rounded-[var(--radius-sm)]" />
        </div>
      </div>

      <OverviewBody>
        <section>
          <SectionHeadSkeleton width="w-28" />
          <Card className="overflow-hidden shadow-card">
            <div className="divide-y divide-[var(--border-subtle)]">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="flex items-start gap-6 px-4 py-3.5 sm:px-5">
                  <div className="min-w-0 flex-1">
                    <Skeleton className="h-3.5 w-[58%] max-w-[320px]" />
                    <Skeleton className="mt-2 h-2.5 w-[34%] max-w-[190px]" />
                    <Skeleton className="mt-3 h-2.5 w-[72%] max-w-[420px]" />
                    <Skeleton className="mt-1.5 h-2.5 w-[42%] max-w-[240px]" />
                  </div>
                  <div className="hidden w-[184px] shrink-0 flex-col items-end gap-2 sm:flex">
                    <Skeleton className="h-3 w-20" />
                    <Skeleton className="h-3 w-24" />
                  </div>
                  <Skeleton className="hidden h-7 w-[104px] shrink-0 rounded-[var(--radius-sm)] sm:block" />
                </div>
              ))}
            </div>
          </Card>
        </section>

        <div className="min-w-0 overflow-hidden">
          <div className="flex min-w-0 rounded-[var(--radius-lg)] border border-[var(--border)]">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className={`flex min-w-0 flex-1 flex-col gap-1.5 px-4 py-3.5 ${
                  i > 0 ? "border-l border-[var(--border)]" : ""
                }`}
              >
                <Skeleton className="h-2.5 w-16" />
                <Skeleton className="h-6 w-10" />
                <Skeleton className="h-2.5 w-24" />
              </div>
            ))}
          </div>
        </div>

        <TableSectionSkeleton rows={5} width="w-20" />
        <TableSectionSkeleton rows={5} width="w-24" />

        <section>
          <SectionHeadSkeleton width="w-28" />
          <div className="grid gap-3 sm:grid-cols-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Card key={i} className="p-3.5">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <Skeleton className="h-3.5 w-[62%]" />
                    <Skeleton className="mt-2 h-2.5 w-[44%]" />
                  </div>
                  <Skeleton className="h-[18px] w-16 rounded-[var(--radius-xs)]" />
                </div>
                <div className="mt-3 border-t border-[var(--border-subtle)] pt-2.5">
                  <Skeleton className="h-2.5 w-full" />
                  <Skeleton className="mt-1.5 h-2.5 w-[70%]" />
                </div>
                <div className="mt-3 flex items-center justify-between">
                  <Skeleton className="h-3 w-16" />
                  <Skeleton className="h-2.5 w-20" />
                </div>
              </Card>
            ))}
          </div>
        </section>

        <section>
          <SectionHeadSkeleton width="w-36" />
          <Card className="overflow-hidden">
            <div className="divide-y divide-[var(--border-subtle)]">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="flex h-11 items-center gap-3 px-4">
                  <Skeleton className="size-1.5 rounded-full" />
                  <Skeleton className="h-2.5 flex-1 max-w-[360px]" />
                  <Skeleton className="hidden h-2.5 w-24 sm:block" />
                  <Skeleton className="h-2.5 w-14" />
                </div>
              ))}
            </div>
          </Card>
        </section>

        <section>
          <SectionHeadSkeleton width="w-32" />
          <Card className="px-4 py-3.5">
            <Skeleton className="h-2 w-full rounded-full" />
            <div className="mt-3.5 flex flex-wrap gap-x-5 gap-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-3 w-20" />
              ))}
            </div>
          </Card>
        </section>

        <Skeleton className="h-2.5 w-72" />
      </OverviewBody>
    </>
  );
}

function SectionHeadSkeleton({ width }: { width: string }) {
  return (
    <div className="mb-3 flex items-center justify-between">
      <Skeleton className={`h-3 ${width}`} />
      <Skeleton className="h-2.5 w-20" />
    </div>
  );
}

function TableSectionSkeleton({ rows, width }: { rows: number; width: string }) {
  return (
    <section>
      <SectionHeadSkeleton width={width} />
      <Card className="overflow-hidden">
        <div className="h-8 border-b border-[var(--border)] bg-[var(--bg-subtle)]" />
        <div className="divide-y divide-[var(--border-subtle)]">
          {Array.from({ length: rows }).map((_, i) => (
            <div key={i} className="flex h-11 items-center gap-3 px-4">
              <Skeleton className="h-2.5 flex-1 max-w-[300px]" />
              <Skeleton className="h-[18px] w-20 rounded-[var(--radius-xs)]" />
              <Skeleton className="h-2.5 w-24" />
              <Skeleton className="h-2.5 w-12" />
            </div>
          ))}
        </div>
      </Card>
    </section>
  );
}
