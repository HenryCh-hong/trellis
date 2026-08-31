import * as React from "react";

/** One column, one max width, one vertical rhythm — shared by the page and its skeleton. */
export function OverviewBody({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto flex w-full min-w-0 max-w-[1100px] flex-col gap-8 px-4 pb-16 pt-6 sm:px-5 md:gap-10 md:pt-8">
      {children}
    </div>
  );
}
