import { Skeleton } from "@/components/ui/primitives";

/** Matches the browse layout exactly, so nothing jumps when the data lands. */
export function BrowseSkeleton() {
  return (
    <div className="flex min-h-0 flex-1">
      <aside className="hidden w-56 shrink-0 flex-col gap-4 border-r border-[var(--border)] bg-[var(--bg-subtle)] px-4 py-4 lg:flex">
        {[5, 4, 6].map((rows, group) => (
          <div key={group} className="flex flex-col gap-1.5">
            <Skeleton className="h-2.5 w-20" />
            {Array.from({ length: rows }).map((_, row) => (
              <Skeleton key={row} className="h-3.5 w-full" />
            ))}
          </div>
        ))}
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-[var(--border)] px-4 py-2.5">
          <Skeleton className="h-7 w-56" />
          <Skeleton className="ml-auto h-7 w-36" />
          <Skeleton className="h-7 w-28" />
        </div>
        <div className="grid gap-3 p-4 lg:grid-cols-2 2xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              className="flex min-h-[200px] flex-col gap-3 rounded-[var(--radius-lg)] border border-[var(--border)] p-3.5"
            >
              <div className="flex items-center justify-between">
                <Skeleton className="h-[18px] w-16" />
                <Skeleton className="h-3 w-16" />
              </div>
              <div className="flex flex-col gap-1.5">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-3 w-1/2" />
              </div>
              <div className="flex gap-1">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-4 w-20" />
              </div>
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-4/5" />
              <div className="mt-auto flex items-center justify-between border-t border-[var(--border-subtle)] pt-2.5">
                <Skeleton className="h-3 w-32" />
                <Skeleton className="h-3 w-16" />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/** Matches the reading column on a lab profile. */
export function LabProfileSkeleton() {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex h-12 shrink-0 items-center gap-3 border-b border-[var(--border)] px-4">
        <Skeleton className="h-3.5 w-24" />
        <Skeleton className="ml-auto h-7 w-40" />
      </div>
      <div className="min-h-0 flex-1 overflow-hidden">
        <div className="mx-auto flex max-w-[860px] flex-col gap-8 px-5 py-8 md:px-8">
          <div className="flex flex-col gap-2">
            <Skeleton className="h-[18px] w-20" />
            <Skeleton className="h-6 w-64" />
            <Skeleton className="h-3.5 w-80" />
            <Skeleton className="h-3.5 w-52" />
          </div>
          {[3, 5, 3].map((rows, section) => (
            <div key={section} className="flex flex-col gap-2 border-t border-[var(--border)] pt-6">
              <Skeleton className="h-2.5 w-40" />
              {Array.from({ length: rows }).map((_, row) => (
                <Skeleton key={row} className="h-3.5 w-full" />
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
