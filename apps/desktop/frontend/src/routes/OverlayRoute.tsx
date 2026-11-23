/**
 * `/overlay` — transparent host. Renders the avatar runtime + speech bubble.
 *
 * No controls live on this route; the docked toolbar and browser dashboard
 * own interaction.
 * The overlay is intentionally minimal so it can be made click-through by
 * the Tauri shell (M8) without interfering with the keyboard focus of
 * other windows.
 */

import { useEffect, useState, type CSSProperties, type WheelEvent } from "react";

import { AvatarHost } from "../components/AvatarHost";
import { AvatarStatusBubble } from "../components/AvatarStatusBubble";
import { SpeechBubble } from "../components/SpeechBubble";
import { useAppearance } from "../hooks/useAppearance";
import { useCharacterSwitchKey } from "../hooks/useCharacterSwitchKey";

type CustomStyle = CSSProperties & Record<`--om-${string}`, string>;

const AVATAR_ZOOM_KEY = "openmimicry.avatar.zoom";
const MIN_ZOOM = 0.35;
const MAX_ZOOM = 2.5;
const ZOOM_STEP = 0.08;

function readSavedZoom(): number {
  try {
    const value = Number(window.localStorage.getItem(AVATAR_ZOOM_KEY));
    return Number.isFinite(value) && value >= MIN_ZOOM && value <= MAX_ZOOM ? value : 1;
  } catch {
    return 1;
  }
}

export function OverlayRoute(): JSX.Element {
  useCharacterSwitchKey();
  const appearance = useAppearance();
  const [zoom, setZoom] = useState<number>(readSavedZoom);

  useEffect(() => {
    try {
      window.localStorage.setItem(AVATAR_ZOOM_KEY, String(zoom));
    } catch {
      // Local storage may be unavailable in browser privacy mode.
    }
  }, [zoom]);

  const handleAvatarWheel = (event: WheelEvent<HTMLDivElement>) => {
    if (!(event.target instanceof Element) || !event.target.closest(".avatar-host")) return;
    event.preventDefault();
    setZoom((current) => {
      const next = current + (event.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP);
      return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Number(next.toFixed(2))));
    });
  };
  const style: CustomStyle = {
    "--om-font-family": appearance.theme.font_family,
    "--om-bubble-bg": appearance.theme.bubble_bg,
    "--om-bubble-text": appearance.theme.bubble_text,
    "--om-bubble-max-width": `${appearance.layout.bubble_max_width}px`,
    "--om-avatar-width": `${appearance.layout.avatar_width}px`,
    "--om-avatar-scale": String(appearance.layout.avatar_scale * zoom),
  };
  return (
    <div className="overlay-route" data-route="overlay" style={style} onWheel={handleAvatarWheel} title="Mouse wheel over character to resize">
      <AvatarStatusBubble />
      <AvatarHost />
      <SpeechBubble timing={appearance.behaviour.bubble} />
    </div>
  );
}
