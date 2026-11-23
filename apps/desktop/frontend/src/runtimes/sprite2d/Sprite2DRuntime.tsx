/**
 * Sprite2DRuntime — the React component that renders frame folders.
 *
 * Subscribes to `avatar.directive` messages with `runtime === "sprite2d"`
 * (delivered via the WS context provided by M7) and advances the current
 * frame index at the rate the projection specifies. `loop=false` clamps
 * at the last frame; `loop=true` wraps.
 *
 * For Benny's photo pack (`ai_girlfriend`) the component picks frame folders
 * itself (Phase 4):
 *   - idle: natural blinking (idle/000-002)
 *   - speaking: RMS lip-sync over `<expression>_speaking` (or `speaking`)
 *   - after speaking: hold the expression still for a few seconds
 * The expression comes from the LLM's structured `emotion`, latched for the
 * whole turn because later lifecycle directives reset emotion to neutral.
 * Folder changes cross-fade; mouth frames inside a folder switch instantly.
 */

import { useEffect, useRef, useState } from "react";

import { preload } from "./preloader";
import { useWS } from "../../ws/WSProvider";

export type Sprite2DProjection = {
  type: "avatar.directive";
  runtime: "sprite2d";
  directive: {
    state: string;
    emotion?: string;
    speaking?: boolean;
    text?: string | null;
    [key: string]: unknown;
  };
  frames: string[];
  fps: number;
  loop: boolean;
  speaking?: boolean;
};

export type Sprite2DRuntimeProps = {
  /** The current projection. Updated by the WS provider on every directive. */
  projection?: Sprite2DProjection;
  /** Optional className passed through to the wrapping element. */
  className?: string;
  /** Default fps applied before the first projection arrives. */
  defaultFps?: number;
};

const DEFAULT_FPS = 10;
const EXPRESSION_HOLD_MS = 4000;
const CROSSFADE_MS = 220;

type Expression = "neutral" | "happy" | "sad" | "angry" | "surprised";

/** Map the LLM's emotion vocabulary onto the photo folders that exist. */
export function expressionForEmotion(emotion: unknown): Expression {
  switch (emotion) {
    // The happy/ and happy_speaking/ smile photos look unnatural, so happy
    // replies keep Benny's original face (idle blink + speaking frames).
    case "sad":
    case "worried":
      return "sad";
    case "angry":
      return "angry";
    case "surprised":
      return "surprised";
    default:
      return "neutral";
  }
}

const PHOTO_BASE = "http://127.0.0.1:8000/static/characters/ai_girlfriend";

const PHOTO_FRAME_COUNTS: Record<string, number> = {
  idle: 3,
  thinking: 4,
  listening: 3,
  speaking: 4,
  happy: 3,
  happy_speaking: 4,
  sad: 1,
  sad_speaking: 4,
  angry: 1,
  angry_speaking: 4,
  surprised: 1,
  surprised_speaking: 4,
};

const TEST_STATES = Object.keys(PHOTO_FRAME_COUNTS);

function photoFrames(folder: string): string[] {
  return Array.from(
    { length: PHOTO_FRAME_COUNTS[folder] ?? 1 },
    (_, index) => `${PHOTO_BASE}/${folder}/${String(index).padStart(3, "0")}.png`
  );
}

type RMSPlayback = {
  utteranceId: string;
  frames: Array<0 | 1 | 2 | 3>;
  windowMs: number;
  startedAt: number;
};

type AnimationMode = "blink" | "still" | "speak" | "cycle";

export function Sprite2DRuntime(props: Sprite2DRuntimeProps) {
  const [currentIdx, setCurrentIdx] = useState<number>(0);
  const ws = useWS();

  // A2 RMS lip-sync state.
  const [rmsPlayback, setRmsPlayback] = useState<RMSPlayback | null>(null);
  const activeUtteranceRef = useRef<string | null>(null);
  const startedAtRef = useRef<number>(0);
  const pendingRmsRef = useRef<
    Map<string, { frames: Array<0 | 1 | 2 | 3>; windowMs: number }>
  >(new Map());

  // Phase 4: expression latched from the LLM cue for the current turn.
  const [expression, setExpression] = useState<Expression>("neutral");
  const [holdingExpression, setHoldingExpression] = useState(false);
  const expressionRef = useRef<Expression>("neutral");
  const holdTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cancelHold = () => {
    if (holdTimerRef.current !== null) {
      clearTimeout(holdTimerRef.current);
      holdTimerRef.current = null;
    }
  };

  const holdExpressionBriefly = () => {
    cancelHold();
    if (expressionRef.current === "neutral") {
      setHoldingExpression(false);
      return;
    }
    setHoldingExpression(true);
    holdTimerRef.current = setTimeout(() => {
      holdTimerRef.current = null;
      setHoldingExpression(false);
      expressionRef.current = "neutral";
      setExpression("neutral");
    }, EXPRESSION_HOLD_MS);
  };

  const resetExpression = () => {
    cancelHold();
    setHoldingExpression(false);
    expressionRef.current = "neutral";
    setExpression("neutral");
  };

  useEffect(() => () => cancelHold(), []);

  const directive = props.projection?.directive;
  const directiveState = directive?.state;
  const directiveEmotion = directive?.emotion;
  const directiveSource = (directive?.metadata as { source?: string } | undefined)?.source;
  const speaking =
    directive?.speaking === true || props.projection?.speaking === true;

  // Latch the LLM's emotion; clear it when a new turn starts.
  useEffect(() => {
    if (directiveSource === "llm_structured_output") {
      const next = expressionForEmotion(directiveEmotion);
      expressionRef.current = next;
      setExpression(next);
      if (activeUtteranceRef.current === null) {
        // Text-only reply (voice off): show the face immediately.
        holdExpressionBriefly();
      } else {
        cancelHold();
      }
    } else if (directiveState === "thinking" || directiveState === "listening") {
      resetExpression();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [directive]);

  const isAiGirlfriend =
    props.projection?.frames?.some((frame) => frame.includes("/ai_girlfriend/")) ?? false;

  const testState = new URLSearchParams(window.location.search).get("aiState");
  const testFolder = testState && TEST_STATES.includes(testState) ? testState : null;

  const speakingNow = rmsPlayback !== null || speaking;
  let photoFolder: string | null = null;
  let mode: AnimationMode = "cycle";
  if (testFolder) {
    photoFolder = testFolder;
    mode = testFolder.endsWith("speaking") ? "speak" : testFolder === "idle" ? "blink" : "still";
  } else if (isAiGirlfriend) {
    if (speakingNow) {
      photoFolder = expression === "neutral" ? "speaking" : `${expression}_speaking`;
      mode = "speak";
    } else if (holdingExpression && expression !== "neutral") {
      photoFolder = expression;
      mode = "still";
    } else {
      // Listening/thinking keep the eyes open; otherwise blink naturally.
      photoFolder = "idle";
      mode = directiveState === "thinking" || directiveState === "listening" ? "still" : "blink";
    }
  }

  const frames = photoFolder ? photoFrames(photoFolder) : props.projection?.frames ?? [];
  const framesKey = frames.join("|");
  const fps = props.projection?.fps ?? props.defaultFps ?? DEFAULT_FPS;
  const loop = props.projection?.loop ?? true;
  const lastFramesRef = useRef<string[]>([]);

  // A2: Receive RMS frames and match them to speech lifecycle events.
  useEffect(() => {
    const offFrames = ws.subscribe("lip_sync.frames", (msg) => {
      const data = { frames: msg.frames, windowMs: msg.window_ms };
      if (activeUtteranceRef.current === msg.utterance_id) {
        setRmsPlayback({
          utteranceId: msg.utterance_id,
          frames: data.frames,
          windowMs: data.windowMs,
          startedAt: startedAtRef.current,
        });
      } else {
        // Azure may publish RMS before speech.status=started.
        pendingRmsRef.current.set(msg.utterance_id, data);
        while (pendingRmsRef.current.size > 4) {
          const oldest = pendingRmsRef.current.keys().next().value;
          if (oldest === undefined) break;
          pendingRmsRef.current.delete(oldest);
        }
      }
    });

    const offSpeech = ws.subscribe("speech.status", (msg) => {
      const id = msg.utterance_id;

      if (msg.status === "queued") {
        activeUtteranceRef.current = null;
        startedAtRef.current = 0;
        setRmsPlayback(null);
        setCurrentIdx(0);
        return;
      }

      if (msg.status === "started" && id) {
        cancelHold();
        setHoldingExpression(false);
        activeUtteranceRef.current = id;
        startedAtRef.current = Date.now();
        const pending = pendingRmsRef.current.get(id);
        pendingRmsRef.current.clear();
        setRmsPlayback(
          pending
            ? {
                utteranceId: id,
                frames: pending.frames,
                windowMs: pending.windowMs,
                startedAt: startedAtRef.current,
              }
            : null
        );
        return;
      }

      if (
        (msg.status === "finished" || msg.status === "interrupted" || msg.status === "failed") &&
        id === activeUtteranceRef.current
      ) {
        activeUtteranceRef.current = null;
        startedAtRef.current = 0;
        if (id !== null) pendingRmsRef.current.delete(id);
        setRmsPlayback(null);
        setCurrentIdx(0);
        if (msg.status === "finished") {
          holdExpressionBriefly();
        } else {
          resetExpression();
        }
      }
    });

    return () => {
      offFrames();
      offSpeech();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ws.subscribe]);

  // Preload + reset index whenever the frame set changes.
  useEffect(() => {
    if (
      frames.length === lastFramesRef.current.length &&
      frames.every((f, i) => f === lastFramesRef.current[i])
    ) {
      return;
    }
    lastFramesRef.current = frames;
    setCurrentIdx(0);
    if (frames.length > 0) {
      preload(frames).catch(() => {
        // already logged via the onError hook
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [framesKey]);

  // Warm the cache with every expression so the first switch never flashes.
  useEffect(() => {
    if (!isAiGirlfriend) return;
    preload(Object.keys(PHOTO_FRAME_COUNTS).flatMap(photoFrames)).catch(() => undefined);
  }, [isAiGirlfriend]);

  // Advance the frame index for the current animation mode.
  useEffect(() => {
    if (frames.length <= 1 || fps <= 0 || mode === "still") {
      setCurrentIdx(0);
      return;
    }

    if (mode === "blink" && frames.length === 3) {
      let cancelled = false;
      let timer: ReturnType<typeof setTimeout>;
      const scheduleBlink = () => {
        const delay = 3000 + Math.random() * 3000;
        timer = setTimeout(() => {
          if (cancelled) return;
          setCurrentIdx(1);
          timer = setTimeout(() => {
            if (cancelled) return;
            setCurrentIdx(2);
            timer = setTimeout(() => {
              if (cancelled) return;
              setCurrentIdx(0);
              scheduleBlink();
            }, 100);
          }, 80);
        }, delay);
      };
      setCurrentIdx(0);
      scheduleBlink();
      return () => {
        cancelled = true;
        clearTimeout(timer);
      };
    }

    // A2: Play RMS frames against the speech-start clock.
    if (mode === "speak" && frames.length === 4 && rmsPlayback !== null) {
      const updateMouth = () => {
        const elapsed = Math.max(0, Date.now() - rmsPlayback.startedAt);
        const position = Math.floor(elapsed / rmsPlayback.windowMs);
        setCurrentIdx(rmsPlayback.frames[position] ?? 0);
      };
      updateMouth();
      const timer = setInterval(updateMouth, 20);
      return () => clearInterval(timer);
    }

    // No RMS data: natural speech animation with varied openings and pauses.
    if (mode === "speak" && frames.length === 4) {
      let cancelled = false;
      let timer: ReturnType<typeof setTimeout>;
      let previousFrame = 0;
      const animateMouth = () => {
        if (cancelled) return;
        const pause = Math.random() < 0.12;
        let nextFrame: number;
        if (pause) {
          nextFrame = 0;
        } else {
          const choices = [1, 2, 3, 2, 1, 0];
          nextFrame = choices[Math.floor(Math.random() * choices.length)] ?? 0;
          if (nextFrame === previousFrame) nextFrame = (nextFrame + 1) % 4;
        }
        previousFrame = nextFrame;
        setCurrentIdx(nextFrame);
        timer = setTimeout(animateMouth, pause ? 130 + Math.random() * 140 : 85 + Math.random() * 95);
      };
      setCurrentIdx(0);
      animateMouth();
      return () => {
        cancelled = true;
        clearTimeout(timer);
      };
    }

    const intervalMs = Math.max(1, Math.floor(1000 / fps));
    const handle = setInterval(() => {
      setCurrentIdx((idx) => {
        const next = idx + 1;
        if (next >= frames.length) return loop ? 0 : frames.length - 1;
        return next;
      });
    }, intervalMs);
    return () => clearInterval(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [framesKey, fps, loop, mode, rmsPlayback]);

  // Cross-fade between folders (expression changes), never between mouth frames.
  const src = frames.length ? frames[Math.min(currentIdx, frames.length - 1)] : undefined;
  const folderKey = photoFolder ?? framesKey;
  const lastShownRef = useRef<{ folder: string; src: string | undefined }>({
    folder: folderKey,
    src,
  });
  const [fadeFrom, setFadeFrom] = useState<{ src: string; key: number } | null>(null);
  useEffect(() => {
    const previous = lastShownRef.current;
    if (previous.folder !== folderKey && previous.src && previous.src !== src) {
      setFadeFrom({ src: previous.src, key: Date.now() });
      const timer = setTimeout(() => setFadeFrom(null), CROSSFADE_MS + 40);
      lastShownRef.current = { folder: folderKey, src };
      return () => clearTimeout(timer);
    }
    lastShownRef.current = { folder: folderKey, src };
    return undefined;
  }, [folderKey, src]);

  if (frames.length === 0) {
    return (
      <div
        className={`avatar avatar--sprite2d avatar--empty ${props.className ?? ""}`}
        data-state="idle"
        data-frames="0"
      />
    );
  }

  const alive = isAiGirlfriend || testFolder !== null;
  return (
    <div
      className={`avatar avatar--sprite2d ${alive ? "avatar--alive" : ""} ${props.className ?? ""}`}
      data-state={directiveState ?? "idle"}
      data-expression={expression}
      data-folder={photoFolder ?? undefined}
      data-frames={String(frames.length)}
      data-frame-idx={String(currentIdx)}
    >
      <div className="avatar-sway">
        <div className={`avatar-stage ${speakingNow ? "avatar-stage--speaking" : ""}`}>
          <img className="avatar-frame" src={src} alt={String(directiveState ?? "avatar")} />
          {fadeFrom ? (
            <img
              key={fadeFrom.key}
              className="avatar-frame avatar-frame--fade-out"
              src={fadeFrom.src}
              alt=""
              aria-hidden="true"
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}
