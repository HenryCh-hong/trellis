"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";

/** Re-runs the server component's fetch without a full page reload. */
export function RetryButton() {
  const router = useRouter();
  const [pending, startTransition] = React.useTransition();

  return (
    <Button
      variant="secondary"
      size="sm"
      loading={pending}
      onClick={() => startTransition(() => router.refresh())}
    >
      Try again
    </Button>
  );
}
