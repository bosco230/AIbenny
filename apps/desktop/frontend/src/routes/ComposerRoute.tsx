import { useEffect, useRef, type CSSProperties } from "react";

import { TextInput } from "../components/TextInput";
import { useAppearance } from "../hooks/useAppearance";
import { useRuntimeState } from "../hooks/useRuntimeState";

type CustomStyle = CSSProperties & Record<`--om-${string}`, string>;

/** Interactive message composer docked underneath the click-through avatar. */
export function ComposerRoute(): JSX.Element {
  const appearance = useAppearance();
  const runtime = useRuntimeState();
  const composerRef = useRef<HTMLDivElement>(null);
  const previousTurnRef = useRef<string | null>(null);

  useEffect(() => {
    const turn = runtime.turn;

    if (turn === null) return;

    const turnKey = `${turn.turn_id}:${turn.state}`;

    if (previousTurnRef.current === turnKey) return;
    previousTurnRef.current = turnKey;

    if (turn.state !== "completed" || !runtime.canSubmit) return;

    // Never steal focus from another browser or desktop window.
    if (!document.hasFocus()) return;

    const input = composerRef.current?.querySelector<HTMLInputElement>(
      'input[aria-label="message"]',
    );

    if (!input || input.disabled) return;

    // Respect a user who has deliberately focused another control.
    const active = document.activeElement;
    if (
      active instanceof HTMLElement &&
      active !== document.body &&
      active !== document.documentElement &&
      active !== input
    ) {
      return;
    }

    input.focus();
  }, [runtime.turn, runtime.canSubmit]);

  const style: CustomStyle = {
    "--om-font-family": appearance.theme.font_family,
    "--om-controls-bg": appearance.theme.controls_bg,
    "--om-controls-border": appearance.theme.controls_border,
    "--om-input-bg": appearance.theme.input_bg,
    "--om-input-border": appearance.theme.input_border,
    "--om-accent": appearance.theme.accent,
  };

  return (
    <div
      ref={composerRef}
      className="composer-route"
      data-route="composer"
      style={style}
    >
      <TextInput
        className="avatar-text-input"
        placeholder={runtime.canSubmit ? "Message OpenMimicry…" : runtime.statusLabel}
        disabled={!runtime.canSubmit}
      />
    </div>
  );
}
