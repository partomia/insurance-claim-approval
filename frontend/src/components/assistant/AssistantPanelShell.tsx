import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { GripHorizontal, Maximize2, Minus, X } from "lucide-react";
import { cn } from "@/lib/utils";

type PanelMode = "normal" | "minimized" | "maximized";

interface PanelSize {
  width: number;
  height: number;
}

interface PanelPosition {
  x: number;
  y: number;
}

interface StoredPanelState {
  mode: PanelMode;
  size: PanelSize;
  position: PanelPosition | null;
}

interface AssistantPanelShellProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  storageKey: string;
  title: string;
  subtitle: string;
  fab: ReactNode;
  headerClassName?: string;
  panelClassName?: string;
  children: ReactNode;
  footer: ReactNode;
  onBackdropClick?: () => void;
}

const DEFAULT_SIZE: PanelSize = { width: 440, height: 580 };
const MIN_SIZE: PanelSize = { width: 320, height: 360 };
const MAX_SIZE: PanelSize = { width: 920, height: 860 };
const VIEWPORT_MARGIN = 16;

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function defaultPosition(size: PanelSize): PanelPosition {
  if (typeof window === "undefined") {
    return { x: VIEWPORT_MARGIN, y: VIEWPORT_MARGIN };
  }
  return {
    x: Math.max(VIEWPORT_MARGIN, window.innerWidth - size.width - 24),
    y: Math.max(VIEWPORT_MARGIN, window.innerHeight - size.height - 24),
  };
}

function clampPosition(position: PanelPosition, size: PanelSize, minimized: boolean): PanelPosition {
  if (typeof window === "undefined") return position;
  const panelWidth = minimized ? 360 : size.width;
  const panelHeight = minimized ? 56 : size.height;
  const maxX = Math.max(VIEWPORT_MARGIN, window.innerWidth - panelWidth - VIEWPORT_MARGIN);
  const maxY = Math.max(VIEWPORT_MARGIN, window.innerHeight - panelHeight - VIEWPORT_MARGIN);
  return {
    x: clamp(position.x, VIEWPORT_MARGIN, maxX),
    y: clamp(position.y, VIEWPORT_MARGIN, maxY),
  };
}

function loadPanelState(storageKey: string): StoredPanelState {
  try {
    const raw = localStorage.getItem(storageKey);
    if (!raw) {
      return { mode: "normal", size: DEFAULT_SIZE, position: null };
    }
    const parsed = JSON.parse(raw) as Partial<StoredPanelState>;
    const size = {
      width: clamp(parsed.size?.width ?? DEFAULT_SIZE.width, MIN_SIZE.width, MAX_SIZE.width),
      height: clamp(parsed.size?.height ?? DEFAULT_SIZE.height, MIN_SIZE.height, MAX_SIZE.height),
    };
    const position = parsed.position
      ? clampPosition(parsed.position, size, parsed.mode === "minimized")
      : null;
    return {
      mode: parsed.mode ?? "normal",
      size,
      position,
    };
  } catch {
    return { mode: "normal", size: DEFAULT_SIZE, position: null };
  }
}

export function AssistantPanelShell({
  open,
  onOpenChange,
  storageKey,
  title,
  subtitle,
  fab,
  headerClassName,
  panelClassName,
  children,
  footer,
  onBackdropClick,
}: AssistantPanelShellProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [{ mode, size, position }, setPanelState] = useState<StoredPanelState>(() => loadPanelState(storageKey));
  const resizeRef = useRef<{ startX: number; startY: number; startW: number; startH: number } | null>(null);
  const dragRef = useRef<{ startX: number; startY: number; originX: number; originY: number } | null>(null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    localStorage.setItem(storageKey, JSON.stringify({ mode, size, position }));
  }, [mode, size, position, storageKey]);

  useEffect(() => {
    if (!open || mode === "minimized") return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open, mode]);

  useEffect(() => {
    if (!open) return;
    setPanelState((prev) => {
      const nextPosition = prev.position ?? defaultPosition(prev.size);
      return { ...prev, position: clampPosition(nextPosition, prev.size, prev.mode === "minimized") };
    });
  }, [open]);

  useEffect(() => {
    const onResize = () => {
      setPanelState((prev) => {
        if (!prev.position || prev.mode === "maximized") return prev;
        return {
          ...prev,
          position: clampPosition(prev.position, prev.size, prev.mode === "minimized"),
        };
      });
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const closePanel = useCallback(() => {
    onOpenChange(false);
  }, [onOpenChange]);

  const handleBackdrop = () => {
    if (onBackdropClick) onBackdropClick();
    else closePanel();
  };

  useEffect(() => {
    const onMove = (event: MouseEvent) => {
      if (dragRef.current) {
        const { startX, startY, originX, originY } = dragRef.current;
        const next = clampPosition(
          {
            x: originX + (event.clientX - startX),
            y: originY + (event.clientY - startY),
          },
          size,
          mode === "minimized"
        );
        setPanelState((prev) => ({ ...prev, position: next, mode: prev.mode === "maximized" ? "normal" : prev.mode }));
        return;
      }

      if (!resizeRef.current) return;
      const { startX, startY, startW, startH } = resizeRef.current;
      const nextWidth = clamp(startW + (startX - event.clientX), MIN_SIZE.width, MAX_SIZE.width);
      const nextHeight = clamp(startH + (startY - event.clientY), MIN_SIZE.height, MAX_SIZE.height);
      setPanelState((prev) => {
        const nextSize = { width: nextWidth, height: nextHeight };
        const nextPosition = prev.position
          ? clampPosition(prev.position, nextSize, false)
          : defaultPosition(nextSize);
        return { ...prev, mode: "normal", size: nextSize, position: nextPosition };
      });
    };

    const onUp = () => {
      dragRef.current = null;
      resizeRef.current = null;
      setDragging(false);
    };

    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [mode, size]);

  const startResize = (event: React.MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
    resizeRef.current = {
      startX: event.clientX,
      startY: event.clientY,
      startW: size.width,
      startH: size.height,
    };
  };

  const startDrag = (event: React.MouseEvent) => {
    if (mode === "maximized") return;
    if ((event.target as HTMLElement).closest("button")) return;

    event.preventDefault();
    const current = position ?? defaultPosition(size);
    dragRef.current = {
      startX: event.clientX,
      startY: event.clientY,
      originX: current.x,
      originY: current.y,
    };
    setPanelState((prev) => ({ ...prev, position: current }));
    setDragging(true);
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => onOpenChange(true)}
        className="fixed bottom-6 right-6 z-[100] hover:scale-105 transition-transform"
        aria-label={`Open ${title}`}
      >
        {fab}
      </button>
    );
  }

  const isMinimized = mode === "minimized";
  const isMaximized = mode === "maximized";
  const panelWidth = isMaximized ? undefined : isMinimized ? 360 : size.width;
  const panelHeight = isMaximized ? undefined : isMinimized ? undefined : size.height;
  const resolvedPosition = position ?? defaultPosition(size);

  const panelStyle: CSSProperties = isMaximized
    ? { inset: VIEWPORT_MARGIN }
    : {
        left: resolvedPosition.x,
        top: resolvedPosition.y,
        width: panelWidth,
        height: panelHeight,
      };

  return (
    <>
      {!isMinimized && (
        <button
          type="button"
          className="assistant-backdrop fixed inset-0 z-[90]"
          aria-label={`Close ${title}`}
          onClick={handleBackdrop}
        />
      )}

      <div
        ref={panelRef}
        role="dialog"
        aria-modal={!isMinimized}
        aria-label={title}
        style={panelStyle}
        className={cn(
          "assistant-panel fixed z-[100] flex flex-col overflow-hidden rounded-2xl shadow-2xl",
          isMinimized && "overflow-visible",
          dragging && "select-none",
          panelClassName
        )}
      >
        <div
          onMouseDown={startDrag}
          className={cn(
            "assistant-header flex items-center justify-between px-4 py-3.5 shrink-0",
            mode !== "maximized" && "cursor-grab active:cursor-grabbing",
            headerClassName
          )}
        >
          <div className="flex items-center gap-2 min-w-0">
            <GripHorizontal className="h-4 w-4 shrink-0 text-white/60" aria-hidden />
            <div className="min-w-0">
              <p className="text-sm font-bold tracking-tight text-white truncate">{title}</p>
              <p className="text-xs text-white/75 truncate">{subtitle}</p>
            </div>
          </div>
          <div className="flex items-center gap-1.5 shrink-0" onMouseDown={(e) => e.stopPropagation()}>
            <button
              type="button"
              onClick={() => setPanelState((prev) => ({ ...prev, mode: isMinimized ? "normal" : "minimized" }))}
              aria-label={isMinimized ? "Restore panel" : "Minimize panel"}
              className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/30 bg-white/10 text-white hover:bg-white/20 transition-colors"
            >
              {isMinimized ? <Maximize2 className="h-3.5 w-3.5" /> : <Minus className="h-3.5 w-3.5" />}
            </button>
            {!isMinimized && (
              <button
                type="button"
                onClick={() =>
                  setPanelState((prev) => ({
                    ...prev,
                    mode: isMaximized ? "normal" : "maximized",
                  }))
                }
                aria-label={isMaximized ? "Restore panel size" : "Maximize panel"}
                className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/30 bg-white/10 text-white hover:bg-white/20 transition-colors"
              >
                <Maximize2 className="h-3.5 w-3.5" />
              </button>
            )}
            <button
              type="button"
              onClick={closePanel}
              aria-label="Close"
              className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/30 bg-white/10 text-white hover:bg-white/20 transition-colors"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {!isMinimized && (
          <>
            <div className="assistant-body flex-1 min-h-0 overflow-y-auto px-3 py-3">{children}</div>
            <div className="assistant-footer shrink-0">{footer}</div>
            {!isMaximized && (
              <button
                type="button"
                aria-label="Resize panel"
                onMouseDown={startResize}
                className="absolute left-2 top-2 h-4 w-4 cursor-nwse-resize rounded-sm border border-border bg-background/80"
              />
            )}
          </>
        )}
      </div>
    </>
  );
}
