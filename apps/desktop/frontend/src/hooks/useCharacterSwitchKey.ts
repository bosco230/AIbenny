/**
 * Press Escape in any Benny window to switch companion (Benny ⇄ 叮當).
 *
 * This is a window-level listener, not a global hotkey: a global Escape
 * would swallow the key in every other Windows application.
 */

import { useEffect } from "react";

export const CHARACTER_SWITCH_URL = "/characters/next";

export function useCharacterSwitchKey(): void {
  useEffect(() => {
    let inFlight = false;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.repeat || inFlight) return;
      if (event.ctrlKey || event.altKey || event.metaKey || event.shiftKey) return;
      event.preventDefault();
      inFlight = true;
      void fetch(CHARACTER_SWITCH_URL, { method: "POST" })
        .catch(() => undefined)
        .finally(() => {
          inFlight = false;
        });
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
}
