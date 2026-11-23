/**
 * Sprite2DRuntime ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â the React component that renders frame folders.
 *
 * Subscribes to `avatar.directive` messages with `runtime === "sprite2d"`
 * (delivered via the WS context provided by M7) and advances the current
 * frame index at the rate the projection specifies. `loop=false` clamps
 * at the last frame; `loop=true` wraps.
 *
 * This component is intentionally dumb. It does not derive state from
 * `RuntimeEvent`s -- the backend's `AvatarOrchestrator` has already done
 * that work, and the result arrives as a fully-resolved Sprite2D
 * projection.
 */

import { useEffect, useRef, useState, type CSSProperties } from "react";

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

export function Sprite2DRuntime(props: Sprite2DRuntimeProps) {
  const [currentIdx, setCurrentIdx] = useState<number>(0);

  // A2 RMS lip-sync state.
  const ws = useWS();

  type RMSPlayback = {
    utteranceId: string;
    frames: Array<0 | 1 | 2 | 3>;
    windowMs: number;
    startedAt: number;
  };

  const [rmsPlayback, setRmsPlayback] =
    useState<RMSPlayback | null>(null);

  const activeUtteranceRef = useRef<string | null>(null);
  const startedAtRef = useRef<number>(0);

  // A3: Keep a happy reaction until speech ends, then show it for 4 seconds.
  const [showHappy, setShowHappy] = useState(false);
  const [happySpeechEnabled, setHappySpeechEnabled] = useState(false); // BENNY_HAPPY_SPEECH_V1
  const happyPendingRef = useRef(false);
  const happyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cancelHappyTimer = () => {
    if (happyTimerRef.current !== null) {
      clearTimeout(happyTimerRef.current);
      happyTimerRef.current = null;
    }
  };

  const showHappyBriefly = () => {
    cancelHappyTimer();
    setShowHappy(true);
    happyTimerRef.current = setTimeout(() => {
      setShowHappy(false);
      happyPendingRef.current = false;
      happyTimerRef.current = null;
    }, 4000);
  };

  const pendingRmsRef = useRef<
    Map<string, { frames: Array<0 | 1 | 2 | 3>; windowMs: number }>
  >(new Map());
  const testState = new URLSearchParams(
    window.location.search
  ).get("aiState");

  const validStates = [
    "idle",
    "speaking",
    "listening",
    "thinking",
    "happy",
    "sad",
    "angry",
    "surprised",
    "sad_speaking",
    "angry_speaking",
    "surprised_speaking",
  ];

  const frameCounts: Record<string, number> = {
    idle: 3,
    thinking: 4,
    happy: 3,
    happy_speaking: 4,
    sad: 1,
    angry: 1,
    surprised: 1,
    sad_speaking: 4,
    angry_speaking: 4,
    surprised_speaking: 4,
    speaking: 4,
    listening: 3,
  };

  const getStateFrames = (state: string): string[] =>
    Array.from(
      { length: frameCounts[state] ?? 1 },
      (_, index) =>
        `http://127.0.0.1:8000/static/characters/ai_girlfriend/${state}/${String(index).padStart(3, "0")}.png`
    );
  const directiveState = props.projection?.directive?.state;
  const speaking =
    props.projection?.directive?.speaking === true ||
    props.projection?.speaking === true;

  const knownState =
    typeof directiveState === "string" &&
    validStates.includes(directiveState)
      ? directiveState
      : "idle";

  // Keep the four-frame speaking animation for RMS. Show the smile only
  // after speech has ended; do not let an old happy directive persist forever.
  const automaticState =
    rmsPlayback !== null
      ? "speaking"
      : showHappy
        ? "happy"
        : speaking
          ? "speaking"
          : knownState === "happy"
            ? "idle"
            : knownState;

  useEffect(() => {
    if (directiveState === "happy") {
      happyPendingRef.current = true;
      setHappySpeechEnabled(true);
      if (activeUtteranceRef.current === null) {
        showHappyBriefly();
      }
    } else if (directiveState === "thinking" || directiveState === "listening") {
      happyPendingRef.current = false;
      setHappySpeechEnabled(false);
      cancelHappyTimer();
      setShowHappy(false);
    }
  }, [directiveState]);

  useEffect(() => () => cancelHappyTimer(), []);

  // Active companion (Benny / 叮當), switched with Escape via /characters/next.
  const [activeCharacter, setActiveCharacter] = useState<string>("benny");
  useEffect(
    () =>
      ws.subscribe("character.active", (msg) => {
        setActiveCharacter(msg.id);
      }),
    [ws.subscribe]
  );

  const isAiGirlfriend =
    activeCharacter === "benny" &&
    (props.projection?.frames?.some((frame) =>
      frame.includes("/ai_girlfriend/")
    ) ??
      false);

  const testFrames =
    testState && validStates.includes(testState)
      ? getStateFrames(testState)
      : null;

  // BENNY_IDLE_SPEAKING_ONLY_109H8G
  // Keep natural blinking and RMS-driven mouth movement.
  const selectedState =
    automaticState === "speaking" ? "speaking" : "idle";
  // 叮當 has two cut-out pictures: standing (idle) and laughing (speaking).
  const dingdongFrames =
    activeCharacter === "dingdong"
      ? [
          `http://127.0.0.1:8000/static/characters/dingdong/${
            selectedState === "speaking" ? "speaking" : "idle"
          }.png`,
        ]
      : null;
  const automaticFrames =
    dingdongFrames ?? (isAiGirlfriend ? getStateFrames(selectedState) : null);
  const frames =
    (activeCharacter === "benny" ? testFrames : null) ??
    automaticFrames ??
    props.projection?.frames ??
    [];
  const framesKey = frames.join("|");
  const fps = props.projection?.fps ?? props.defaultFps ?? DEFAULT_FPS;
  const loop = props.projection?.loop ?? true;
  const lastFramesRef = useRef<string[]>([]);

  // A2: Receive RMS frames and match them to speech lifecycle events.
  useEffect(() => {
    const offFrames = ws.subscribe("lip_sync.frames", (msg) => {
      const data = {
        frames: msg.frames,
        windowMs: msg.window_ms,
      };

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

        // Prevent unlimited growth from abandoned utterances.
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
        cancelHappyTimer();
        setShowHappy(false);
        activeUtteranceRef.current = null;
        startedAtRef.current = 0;
        setRmsPlayback(null);
        setCurrentIdx(0);
        return;
      }

      if (msg.status === "started" && id) {
        cancelHappyTimer();
        setShowHappy(false);
        activeUtteranceRef.current = id;
        startedAtRef.current = Date.now();

        const pending = pendingRmsRef.current.get(id);
        pendingRmsRef.current.clear();

        if (pending) {
          setRmsPlayback({
            utteranceId: id,
            frames: pending.frames,
            windowMs: pending.windowMs,
            startedAt: startedAtRef.current,
          });
        } else {
          setRmsPlayback(null);
        }
        return;
      }

      if (
        (msg.status === "finished" ||
          msg.status === "interrupted" ||
          msg.status === "failed") &&
        id === activeUtteranceRef.current
      ) {
        activeUtteranceRef.current = null;
        startedAtRef.current = 0;
        if (id !== null) {
          pendingRmsRef.current.delete(id);
        }
        setRmsPlayback(null);
        setCurrentIdx(0);
        setHappySpeechEnabled(false);
        if (msg.status === "finished" && happyPendingRef.current) {
          showHappyBriefly();
        } else {
          happyPendingRef.current = false;
        }
      }
    });

    return () => {
      offFrames();
      offSpeech();
    };
  }, [ws.subscribe]);

  // Preload + reset index whenever the frame set changes.
  useEffect(() => {
    if (frames === lastFramesRef.current) return;
    if (
      frames.length === lastFramesRef.current.length &&
      frames.every((f, i) => f === lastFramesRef.current[i])
    ) {
      return;
    }
    lastFramesRef.current = frames;
    setCurrentIdx(0);
    if (frames.length > 0) {
      // Fire-and-forget; the renderer is happy to show partially-loaded
      // frames since the cache is populated by the preloader.
      preload(frames).catch(() => {
        // already logged via the onError hook
      });
    }
  }, [frames]);

  // Advance the frame index at the configured rate.
  useEffect(() => {
    if (frames.length <= 1 || fps <= 0) {
      return;
    }
    // The existing happy/000.png is the smiling frame; the other two are
    // neutral, so hold frame zero instead of cycling away from the smile.
    // BENNY_THINKING_STILL_109H8K
    // Keep eyes open while thinking or listening.
    if (
      automaticState === "thinking" ||
      automaticState === "listening" ||
      automaticState === "happy"
    ) {
      setCurrentIdx(0);
      return;
    }

    // Natural blinking for the AI companion in idle state.
    if (automaticState === "idle" && frames.length === 3) {
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
    // Do not loop RMS data after its audio window has ended.
    if (
      automaticState === "speaking" &&
      frames.length === 4 &&
      rmsPlayback !== null
    ) {
      const updateMouth = () => {
        const elapsed = Math.max(0, Date.now() - rmsPlayback.startedAt);
        const position = Math.floor(elapsed / rmsPlayback.windowMs);
        const mouth = rmsPlayback.frames[position] ?? 0;
        setCurrentIdx(mouth);
      };

      updateMouth();
      const timer = setInterval(updateMouth, 20);
      return () => clearInterval(timer);
    }

    // Natural speech animation: varied mouth openings and brief pauses.
    if (automaticState === "speaking" && frames.length === 4) {
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

          if (nextFrame === previousFrame) {
            nextFrame = (nextFrame + 1) % 4;
          }
        }

        previousFrame = nextFrame;
        setCurrentIdx(nextFrame);

        const delay = pause
          ? 130 + Math.random() * 140
          : 85 + Math.random() * 95;

        timer = setTimeout(animateMouth, delay);
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
        if (next >= frames.length) {
          return loop ? 0 : frames.length - 1;
        }
        return next;
      });
    }, intervalMs);
    return () => clearInterval(handle);
  }, [framesKey, fps, loop, automaticState, rmsPlayback]);

  // 叮當: follow speech loudness (RMS mouth level 0-3) with a squash/stretch.
  const isDingdong = activeCharacter === "dingdong" && dingdongFrames !== null;
  const [ddLevel, setDdLevel] = useState(0);
  useEffect(() => {
    if (!isDingdong || rmsPlayback === null) {
      setDdLevel(0);
      return;
    }
    const update = () => {
      const elapsed = Math.max(0, Date.now() - rmsPlayback.startedAt);
      setDdLevel(rmsPlayback.frames[Math.floor(elapsed / rmsPlayback.windowMs)] ?? 0);
    };
    update();
    const timer = setInterval(update, 40);
    return () => clearInterval(timer);
  }, [isDingdong, rmsPlayback]);

  if (frames.length === 0) {
    return (
      <div
        className={`avatar avatar--sprite2d avatar--empty ${props.className ?? ""}`}
        data-state="idle"
        data-frames="0"
      />
    );
  }

  const src = frames[Math.min(currentIdx, frames.length - 1)];

  if (isDingdong) {
    const ddSpeaking = selectedState === "speaking";
    return (
      <div
        className={`avatar avatar--sprite2d avatar--dingdong ${
          ddSpeaking ? "avatar--dd-speaking" : "avatar--dd-idle"
        } ${props.className ?? ""}`}
        data-state={props.projection?.directive?.state ?? "idle"}
        data-frames={String(frames.length)}
        data-frame-idx={String(currentIdx)}
        style={{ "--dd-level": String(ddLevel) } as CSSProperties}
      >
        {/* motion: idle bob/sway or talking bounce; pop: replays on picture change */}
        <div className="dd-motion">
          <div className="dd-pop" key={src}>
            <img
              className="avatar-frame dd-frame"
              src={src}
              alt={String(props.projection?.directive?.state ?? "avatar")}
            />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`avatar avatar--sprite2d ${props.className ?? ""}`}
      data-state={props.projection?.directive?.state ?? "idle"}
      data-frames={String(frames.length)}
      data-frame-idx={String(currentIdx)}
    >
      <img
        className="avatar-frame"
        src={src}
        alt={String(props.projection?.directive?.state ?? "avatar")}
      />
    </div>
  );
}


