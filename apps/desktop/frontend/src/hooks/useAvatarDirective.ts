/**
 * `useAvatarDirective` â€” subscribe to `avatar.directive` messages.
 *
 * Returns the most recent `AvatarDirectiveMessage`. Per `contracts.md`
 * Â§9 the same wire shape carries the full `AvatarDirective` plus
 * runtime-specific extras (frames/fps/loop for Sprite2D, â€¦). Callers
 * pick out what they need.
 */

import { useEffect, useState } from "react";

import { useWS } from "../ws/WSProvider";
import type { AvatarDirectiveMessage } from "../ws/protocol";

export function useAvatarDirective(): AvatarDirectiveMessage | null {
  const ws = useWS();
  const [directive, setDirective] = useState<AvatarDirectiveMessage | null>(
    null,
  );

  useEffect(() => {
    return ws.subscribe("avatar.directive", (msg) => {
      setDirective((previous) => {
        if (!previous) return msg;

        const hasFullProjection =
          msg.directive !== undefined ||
          msg.frames !== undefined;

        if (hasFullProjection) {
          return msg;
        }

        if (typeof msg.speaking === "boolean") {
          return {
            ...previous,
            ...msg,
            directive: previous.directive
              ? {
                  ...previous.directive,
                  speaking: msg.speaking,
                }
              : undefined,
          };
        }

        return { ...previous, ...msg };
      });
    });
  }, [ws]);

  return directive;
}

