import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { X, CheckCircle2, AlertCircle, Info } from "lucide-react";

export type ToastVariant = "success" | "error" | "info";

export interface Toast {
  id: string;
  message: string;
  variant: ToastVariant;
}

interface ToastContextValue {
  toast: (message: string, variant?: ToastVariant) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const VARIANT_STYLES: Record<ToastVariant, string> = {
  success: "border-success-border bg-success-subtle text-foreground [&_svg]:text-success",
  error: "border-destructive/40 bg-destructive/10 text-foreground [&_svg]:text-destructive",
  info: "border-info-border bg-info-subtle text-foreground [&_svg]:text-info",
};

const VARIANT_ICONS: Record<ToastVariant, typeof Info> = {
  success: CheckCircle2,
  error: AlertCircle,
  info: Info,
};

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: string) => void }) {
  const Icon = VARIANT_ICONS[toast.variant];

  return (
    <div
      role="alert"
      className={`flex items-start gap-3 min-w-[280px] max-w-sm p-4 rounded-lg border shadow-lg animate-in slide-in-from-top-2 fade-in duration-200 ${VARIANT_STYLES[toast.variant]}`}
    >
      <Icon className="w-5 h-5 shrink-0 mt-0.5" />
      <p className="text-sm flex-1 leading-snug">{toast.message}</p>
      <button
        type="button"
        onClick={() => onDismiss(toast.id)}
        className="shrink-0 opacity-60 hover:opacity-100 transition-opacity"
        aria-label="Dismiss"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback((message: string, variant: ToastVariant = "info") => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setToasts((prev) => [...prev, { id, message, variant }]);
    setTimeout(() => dismiss(id), 5000);
  }, [dismiss]);

  // Stable references so consumers can safely list these in effect/useCallback
  // dependency arrays without causing infinite re-render loops.
  const success = useCallback((msg: string) => addToast(msg, "success"), [addToast]);
  const error = useCallback((msg: string) => addToast(msg, "error"), [addToast]);
  const info = useCallback((msg: string) => addToast(msg, "info"), [addToast]);

  const value: ToastContextValue = useMemo(
    () => ({ toast: addToast, success, error, info }),
    [addToast, success, error, info]
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        className="fixed top-4 right-4 z-[100] flex flex-col gap-2 pointer-events-none"
      >
        {toasts.map((t) => (
          <div key={t.id} className="pointer-events-auto">
            <ToastItem toast={t} onDismiss={dismiss} />
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within ToastProvider");
  }
  return ctx;
}

/** Normalize FastAPI error detail into a readable string. */
export function formatApiError(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((e) => (typeof e === "object" && e && "msg" in e ? String(e.msg) : String(e))).join(", ");
  }
  if (detail && typeof detail === "object") {
    const obj = detail as Record<string, unknown>;
    if (Array.isArray(obj.errors)) return obj.errors.join(", ");
    if (typeof obj.message === "string") return obj.message;
  }
  return "Something went wrong. Please try again.";
}
