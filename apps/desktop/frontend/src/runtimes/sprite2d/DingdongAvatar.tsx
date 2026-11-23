/**
 * 叮當 — the original screen-face robot (scripts/make_dingdong_svg.py).
 *
 * faces/<expression>/000.svg is the resting mouth, 001-003 speaking mouths.
 * The LLM's emotion is latched for the turn (later lifecycle directives
 * reset emotion to neutral), shown while speaking with RMS lip-sync, held
 * for a few seconds afterwards, then 叮當 returns to his blinking idle face.
 */

import { useEffect, useRef, useState, type CSSProperties } from "react";

import { preload } from "./preloader";

export type DingdongFace =
  | "neutral"
  | "smile"
  | "happy"
  | "sad"
  | "angry"
  | "surprised"
  | "worried"
  | "thinking";

const FACES: DingdongFace[] = [
  "neutral", "smile", "happy", "sad", "angry", "surprised", "worried", "thinking",
];
const BASE = "http://127.0.0.1:8000/static/characters/dingdong/faces";
const HOLD_MS = 4000;

export const dingdongFrame = (face: DingdongFace, level: number): string =>
  `${BASE}/${face}/${String(level).padStart(3, "0")}.svg`;
const BLINK: Partial<Record<DingdongFace, string>> = {
  neutral: `${BASE}/blink.svg`,
  smile: `${BASE}/smile_blink.svg`,
};

/** LLM emotion (+ intensity) -> 叮當's face. Gentle joy smiles, big joy laughs. */
export function dingdongFaceFor(emotion: unknown, intensity: unknown): DingdongFace {
  switch (emotion) {
    case "happy":
      return typeof intensity === "number" && intensity >= 0.6 ? "happy" : "smile";
    case "sad":
      return "sad";
    case "angry":
      return "angry";
    case "surprised":
      return "surprised";
    case "worried":
      return "worried";
    case "confused":
    case "focused":
      return "thinking";
    default:
      return "neutral";
  }
}

type Rms = { frames: Array<0 | 1 | 2 | 3>; windowMs: number; startedAt: number };

export type DingdongAvatarProps = {
  speaking: boolean;
  rms: Rms | null;
  directive?: { state?: string; emotion?: string; [key: string]: unknown };
  className?: string;
};

export function DingdongAvatar({ speaking, rms, directive, className }: DingdongAvatarProps) {
  const [latched, setLatched] = useState<DingdongFace>("neutral");
  const [holding, setHolding] = useState(false);
  const [level, setLevel] = useState(0);
  const [blinking, setBlinking] = useState(false);
  const holdTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wasSpeaking = useRef(false);

  const cancelHold = () => {
    if (holdTimer.current !== null) clearTimeout(holdTimer.current);
    holdTimer.current = null;
  };
  const holdThenRelax = () => {
    cancelHold();
    setHolding(true);
    holdTimer.current = setTimeout(() => {
      holdTimer.current = null;
      setHolding(false);
      setLatched("neutral");
    }, HOLD_MS);
  };

  useEffect(() => {
    preload([...FACES.flatMap((f) => [0, 1, 2, 3].map((l) => dingdongFrame(f, l))), ...Object.values(BLINK)]).catch(
      () => undefined
    );
    return cancelHold;
  }, []);

  // Latch the LLM's emotion; a new turn (listening/thinking) clears it.
  const source = (directive?.metadata as { source?: string } | undefined)?.source;
  useEffect(() => {
    if (source === "llm_structured_output") {
      setLatched(dingdongFaceFor(directive?.emotion, directive?.intensity));
      if (!speaking) holdThenRelax();
      else cancelHold();
    } else if (directive?.state === "listening" || directive?.state === "thinking") {
      cancelHold();
      setHolding(false);
      setLatched("neutral");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [directive]);

  // Speech ended: keep the expression a little longer, then relax.
  useEffect(() => {
    if (speaking) cancelHold();
    else if (wasSpeaking.current) holdThenRelax();
    wasSpeaking.current = speaking;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [speaking]);

  // Mouth: RMS loudness when available, otherwise a natural talking loop.
  useEffect(() => {
    if (!speaking) {
      setLevel(0);
      return;
    }
    if (rms !== null) {
      const update = () => {
        const elapsed = Math.max(0, Date.now() - rms.startedAt);
        setLevel(rms.frames[Math.floor(elapsed / rms.windowMs)] ?? 0);
      };
      update();
      const timer = setInterval(update, 40);
      return () => clearInterval(timer);
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const talk = () => {
      if (cancelled) return;
      const pause = Math.random() < 0.15;
      setLevel(pause ? 0 : 1 + Math.floor(Math.random() * 3));
      timer = setTimeout(talk, pause ? 140 + Math.random() * 120 : 90 + Math.random() * 90);
    };
    talk();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [speaking, rms]);

  const thinking = directive?.state === "thinking";
  const face: DingdongFace = speaking
    ? latched === "thinking" ? "neutral" : latched
    : holding
      ? latched
      : thinking
        ? "thinking"
        : "neutral";

  // Natural blinking whenever the resting face has a blink frame.
  const canBlink = !speaking && BLINK[face] !== undefined;
  useEffect(() => {
    if (!canBlink) {
      setBlinking(false);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const schedule = () => {
      timer = setTimeout(() => {
        if (cancelled) return;
        setBlinking(true);
        timer = setTimeout(() => {
          if (cancelled) return;
          setBlinking(false);
          schedule();
        }, 130);
      }, 2800 + Math.random() * 3200);
    };
    schedule();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [canBlink, face]);

  const src = blinking && canBlink ? (BLINK[face] as string) : dingdongFrame(face, speaking ? level : 0);
  return (
    <div
      className={`avatar avatar--sprite2d avatar--dingdong ${
        speaking ? "avatar--dd-speaking" : "avatar--dd-idle"
      } ${className ?? ""}`}
      data-state={directive?.state ?? "idle"}
      data-face={face}
      data-mouth={String(speaking ? level : 0)}
      style={{ "--dd-level": String(speaking ? level : 0) } as CSSProperties}
    >
      {/* motion: idle bob or talking bounce; pop replays when the expression changes */}
      <div className="dd-motion">
        <div className="dd-pop" key={face}>
          <img className="avatar-frame dd-frame" src={src} alt={`叮當 ${face}`} />
        </div>
      </div>
    </div>
  );
}
