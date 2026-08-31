"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * A toast may carry one action, and it is there for undo.
 *
 * Anything the app does on your behalf that removes something from view has to
 * be reversible in the same gesture, without hunting for where it went — so the
 * action lives on the message that announces it, and the toast stays up long
 * enough to be read and clicked.
 */
type ToastAction = { label: string; onClick: () => void };

type Toast = {
  id: number;
  message: string;
  tone: "default" | "error" | "success";
  action?: ToastAction;
};

const SHORT_MS = 4200;
/** Long enough to notice, read and reach — an undo you miss is not an undo. */
const ACTION_MS = 9000;

const ToastCtx = React.createContext<{
  push: (message: string, tone?: Toast["tone"], action?: ToastAction) => void;
}>({ push: () => {} });

export function useToast() {
  return React.useContext(ToastCtx);
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<Toast[]>([]);
  const idRef = React.useRef(0);

  const dismiss = React.useCallback((id: number) => {
    setToasts((t) => t.filter((x) => x.id !== id));
  }, []);

  const push = React.useCallback(
    (message: string, tone: Toast["tone"] = "default", action?: ToastAction) => {
      const id = ++idRef.current;
      setToasts((t) => [...t, { id, message, tone, action }]);
      setTimeout(() => dismiss(id), action ? ACTION_MS : SHORT_MS);
    },
    [dismiss],
  );

  return (
    <ToastCtx.Provider value={{ push }}>
      {children}
      <div className="pointer-events-none fixed bottom-4 left-1/2 z-[100] flex -translate-x-1/2 flex-col items-center gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className={cn(
              "pointer-events-auto flex animate-rise items-center gap-3 rounded-[var(--radius-md)]",
              "px-3 py-2 text-xs shadow-pop",
              "border max-w-[420px]",
              t.tone === "error"
                ? "bg-[var(--color-danger-50)] border-[var(--color-danger-200)] text-[var(--color-danger-700)]"
                : t.tone === "success"
                  ? "bg-[var(--color-success-50)] border-[var(--color-success-200)] text-[var(--color-success-700)]"
                  : "bg-[var(--color-neutral-900)] border-transparent text-[var(--color-neutral-50)]",
            )}
          >
            <span className="min-w-0">{t.message}</span>
            {t.action && (
              <button
                type="button"
                onClick={() => {
                  dismiss(t.id);
                  t.action?.onClick();
                }}
                className={cn(
                  "shrink-0 font-medium underline underline-offset-2",
                  "transition-opacity duration-100 hover:opacity-80",
                )}
              >
                {t.action.label}
              </button>
            )}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
