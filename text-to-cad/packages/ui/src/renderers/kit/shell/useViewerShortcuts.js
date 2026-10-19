import { useEffect, useRef } from "react";
import { isEditableTarget } from "../viewport/dom.js";

/**
 * Keyboard routing for one mounted viewer among several. Escape reaches
 * `onEscape` only when this viewer owns it: focus is inside it, or the key
 * landed on the page background after the last pointer press was inside it.
 * A composer, another pane and any editable target keep their own Escape.
 *
 * Delete (or Backspace) reaches `onDelete` the same way, for what Select has picked; it is the
 * key's only while `onDelete` says it deleted something. ⌘Z (Ctrl+Z) reaches `onUndo`, and ⇧⌘Z or
 * Ctrl+Y `onRedo`, the same way; a text field keeps its own.
 *
 * @param {{ viewerElement: { current: HTMLElement | null } | null, escapeActive: boolean,
 *   onEscape: (event: KeyboardEvent) => void, onCopy?: () => boolean, onDelete?: () => boolean,
 *   onUndo?: () => boolean, onRedo?: () => boolean }} options
 *   `escapeActive`: there is something for Escape to do (so idle viewers hold no listener).
 */
export function useViewerShortcuts({
  viewerElement, escapeActive, onEscape, onCopy, onDelete, onUndo, onRedo
}) {
  const pointerInside = useRef(false);
  const copy = useRef(onCopy);
  copy.current = onCopy;
  const escape = useRef(onEscape);
  escape.current = onEscape;
  const remove = useRef(onDelete);
  remove.current = onDelete;
  const undo = useRef(onUndo);
  undo.current = onUndo;
  const redo = useRef(onRedo);
  redo.current = onRedo;
  useEffect(() => {
    const onPointerDown = event => { pointerInside.current = Boolean(viewerElement?.current?.contains(event.target)); };
    window.addEventListener("pointerdown", onPointerDown, true);
    return () => window.removeEventListener("pointerdown", onPointerDown, true);
  }, [viewerElement]);
  useEffect(() => {
    if (!(escapeActive || onCopy || onDelete || onUndo || onRedo)) return undefined;
    const handleKeyDown = (event) => {
      const element = viewerElement?.current;
      if (!element) return;
      const target = event.target;
      const inViewer = target instanceof Node && element.contains(target);
      const background = target === document.body || target === document || target === window;
      const focus = document.activeElement;
      if (!inViewer && !(background && pointerInside.current && (focus === document.body || (focus && element.contains(focus))))) return;
      if (!event.defaultPrevented && !isEditableTarget(target) && !window.getSelection()?.toString() &&
          ((event.key.toLowerCase() === "c" && (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey) || (event.key === "Insert" && event.ctrlKey))) {
        if (copy.current?.()) { event.preventDefault(); event.stopPropagation(); }
      }
      if (event.key === "Escape" && !event.defaultPrevented && !isEditableTarget(event.target)) escape.current?.(event);
      if ((event.key === "Delete" || event.key === "Backspace") && !event.defaultPrevented && !isEditableTarget(event.target)
        && remove.current?.()) { event.preventDefault(); event.stopPropagation(); }
      if ((event.metaKey || event.ctrlKey) && !event.altKey && !event.defaultPrevented && !isEditableTarget(event.target)) {
        const key = event.key.toLowerCase();
        const step = key === "z" ? (event.shiftKey ? redo : undo) : key === "y" && event.ctrlKey && !event.shiftKey ? redo : null;
        if (step?.current?.()) { event.preventDefault(); event.stopPropagation(); }
      }
    };
    window.addEventListener("keydown", handleKeyDown, true);
    return () => window.removeEventListener("keydown", handleKeyDown, true);
  }, [viewerElement, escapeActive, Boolean(onCopy), Boolean(onDelete), Boolean(onUndo), Boolean(onRedo)]);
}
