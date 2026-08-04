import { useCallback, useEffect, useRef } from "react";
import { useI18n } from "../i18n";

export type SheetState = "closed" | "half" | "full";

const NEXT_ON_TAP: Record<SheetState, SheetState> = {
  closed: "half",
  half: "full",
  full: "half",
};

const PREV_ON_ESCAPE: Record<SheetState, SheetState> = {
  closed: "closed",
  half: "closed",
  full: "half",
};

// Only "closed"/"half" have a fixed, small visible height (see
// .bottom-sheet-* rules in global.css) -- "full" is simply translateY(0),
// i.e. the sheet's own full (CSS-defined) height, so it needs no pixel
// constant here.
const CLOSED_VISIBLE_PX = 132;
const HALF_VISIBLE_FRACTION = 0.55; // matches --sheet-half-hidden in global.css

const MOBILE_QUERY = "(max-width: 860px)";

function isMobile(): boolean {
  return typeof window !== "undefined" && window.matchMedia(MOBILE_QUERY).matches;
}

export interface BottomSheetProps {
  state: SheetState;
  onStateChange: (state: SheetState) => void;
  children: React.ReactNode;
}

// Mobile-only bottom sheet wrapping the location panel content (item 1):
// closed (headline + swipe hint only), half (headline + advice + timeline +
// tomorrow), full (everything, scrollable). Desktop renders the exact same
// children in the existing static side panel -- .bottom-sheet-handle is
// display:none above the mobile breakpoint (see global.css), and none of
// the drag/pointer logic below does anything when !isMobile().
export function BottomSheet({ state, onStateChange, children }: BottomSheetProps) {
  const { t } = useI18n();
  const rootRef = useRef<HTMLDivElement | null>(null);
  const draggingRef = useRef(false);
  const movedRef = useRef(false);
  const startYRef = useRef(0);
  const startTranslateRef = useRef(0);

  function translateForState(s: SheetState, sheetHeightPx: number): number {
    if (s === "closed") return Math.max(0, sheetHeightPx - CLOSED_VISIBLE_PX);
    if (s === "half") return sheetHeightPx * HALF_VISIBLE_FRACTION;
    return 0;
  }

  function nearestState(translatePx: number, sheetHeightPx: number): SheetState {
    const candidates: SheetState[] = ["full", "half", "closed"];
    let best: SheetState = "half";
    let bestDist = Infinity;
    for (const c of candidates) {
      const dist = Math.abs(translateForState(c, sheetHeightPx) - translatePx);
      if (dist < bestDist) {
        bestDist = dist;
        best = c;
      }
    }
    return best;
  }

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (!isMobile() || !rootRef.current) return;
      draggingRef.current = true;
      movedRef.current = false;
      startYRef.current = e.clientY;
      startTranslateRef.current = translateForState(state, rootRef.current.offsetHeight);
      rootRef.current.classList.add("dragging");
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
    },
    [state]
  );

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!draggingRef.current || !rootRef.current) return;
    const delta = e.clientY - startYRef.current;
    if (Math.abs(delta) > 6) movedRef.current = true;
    const sheetHeightPx = rootRef.current.offsetHeight;
    const maxTranslate = Math.max(0, sheetHeightPx - CLOSED_VISIBLE_PX);
    const next = Math.min(maxTranslate, Math.max(0, startTranslateRef.current + delta));
    rootRef.current.style.setProperty("--sheet-drag-y", `${next}px`);
  }, []);

  const endDrag = useCallback(
    (e: React.PointerEvent) => {
      if (!draggingRef.current || !rootRef.current) return;
      draggingRef.current = false;
      rootRef.current.classList.remove("dragging");
      const sheetHeightPx = rootRef.current.offsetHeight;
      const delta = e.clientY - startYRef.current;
      const finalTranslate = Math.min(
        Math.max(0, sheetHeightPx - CLOSED_VISIBLE_PX),
        Math.max(0, startTranslateRef.current + delta)
      );
      rootRef.current.style.removeProperty("--sheet-drag-y");
      onStateChange(nearestState(finalTranslate, sheetHeightPx));
    },
    [onStateChange]
  );

  function handleTap() {
    if (movedRef.current) {
      movedRef.current = false;
      return;
    }
    if (!isMobile()) return;
    onStateChange(NEXT_ON_TAP[state]);
  }

  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    function onKeyDown(e: KeyboardEvent) {
      if (!isMobile()) return;
      if (e.key === "Escape") {
        onStateChange(PREV_ON_ESCAPE[state]);
      } else if (e.key === "ArrowUp") {
        onStateChange(NEXT_ON_TAP[state]);
      } else if (e.key === "ArrowDown") {
        onStateChange(PREV_ON_ESCAPE[state]);
      }
    }
    el.addEventListener("keydown", onKeyDown);
    return () => el.removeEventListener("keydown", onKeyDown);
  }, [state, onStateChange]);

  return (
    <div ref={rootRef} className={`panel-area bottom-sheet bottom-sheet--${state}`}>
      <div className="bottom-sheet-surface">
        <button
          type="button"
          className="bottom-sheet-handle"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          onClick={handleTap}
          aria-expanded={state !== "closed"}
          aria-label={state === "full" ? t("sheet.collapse") : t("sheet.expand")}
          title={t("sheet.dragHandleLabel")}
        >
          <span className="bottom-sheet-grabber" aria-hidden="true" />
          {state === "closed" && (
            <span className="bottom-sheet-swipe-hint" aria-hidden="true">
              &#9650; {t("sheet.swipeUp")}
            </span>
          )}
        </button>
        <div className="bottom-sheet-scroll">{children}</div>
      </div>
    </div>
  );
}
