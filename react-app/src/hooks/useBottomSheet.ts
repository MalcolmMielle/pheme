import { useCallback, useRef, useState } from "react";

export type SheetState = "peek" | "expanded";

/**
 * Mobile bottom-sheet drag logic: dragging the handle up expands the sheet,
 * dragging down collapses it, and a tap toggles between the two states.
 *
 * Returns the current state, the live drag offset (px, while dragging) and
 * pointer handlers for the handle element.
 */
export function useBottomSheet() {
  const [sheet, setSheet] = useState<SheetState>("peek");
  const [dragDy, setDragDy] = useState<number | null>(null);
  const drag = useRef<{ startY: number; moved: boolean } | null>(null);
  // True right after a pointer tap, so the follow-up click event (which
  // mouse/touch also fire) doesn't toggle a second time. Keyboard activation
  // has no pointerup, so it toggles through onHandleClick directly.
  const handled = useRef(false);

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    drag.current = { startY: e.clientY, moved: false };
    e.currentTarget.setPointerCapture(e.pointerId);
  }, []);

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!drag.current) return;
    const dy = e.clientY - drag.current.startY;
    if (Math.abs(dy) > 4) drag.current.moved = true;
    setDragDy(dy);
  }, []);

  const finishDrag = useCallback((e: React.PointerEvent) => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    const dy = e.clientY - d.startY;
    setDragDy(null);
    if (!d.moved && Math.abs(dy) < 8) {
      // Tap — toggle, and flag so the synthetic click is ignored.
      handled.current = true;
      setSheet((s) => (s === "peek" ? "expanded" : "peek"));
    } else if (dy <= -48) {
      setSheet("expanded");
    } else if (dy >= 48) {
      setSheet("peek");
    }
    // Otherwise the drag was too small — snap back to the current state.
  }, []);

  const onPointerUp = useCallback(
    (e: React.PointerEvent) => finishDrag(e),
    [finishDrag],
  );

  const onPointerCancel = useCallback(() => {
    drag.current = null;
    setDragDy(null);
  }, []);

  const onHandleClick = useCallback(() => {
    if (handled.current) {
      handled.current = false;
      return;
    }
    setSheet((s) => (s === "peek" ? "expanded" : "peek"));
  }, []);

  return {
    sheet,
    dragDy,
    onPointerDown,
    onPointerMove,
    onPointerUp,
    onPointerCancel,
    onHandleClick,
  };
}
