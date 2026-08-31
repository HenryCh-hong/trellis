"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

type Toast = { id: number; message: string; tone: "default" | "error" | "success" };

const ToastCtx = React.createContext<{
  push: (message: string, tone?: Toast["tone"]) => void;
}>({ push: () => {} });

export function useToast() {
  return React.useContext(ToastCtx);
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<Toast[]>([]);
  const idRef = React.useRef(0);

  const push = React.useCallback((message: string, tone: Toast["tone"] = "default") => {
    const id = ++idRef.current;
    setToasts((t) => [...t, { id, message, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4200);
  }, []);

  return (
    <ToastCtx.Provider value={{ push }}>
      {children}
      <div className="pointer-events-none fixed bottom-4 left-1/2 z-[100] flex -translate-x-1/2 flex-col items-center gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className={cn(
              "pointer-events-auto animate-rise rounded-[var(--radius-md)] px-3 py-2 text-xs shadow-pop",
              "border max-w-[420px]",
              t.tone === "error"
                ? "bg-[var(--color-danger-50)] border-[var(--color-danger-200)] text-[var(--color-danger-700)]"
                : t.tone === "success"
                  ? "bg-[var(--color-success-50)] border-[var(--color-success-200)] text-[var(--color-success-700)]"
                  : "bg-[var(--color-neutral-900)] border-transparent text-[var(--color-neutral-50)]",
            )}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
