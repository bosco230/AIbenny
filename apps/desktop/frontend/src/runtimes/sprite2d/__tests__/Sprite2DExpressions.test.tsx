import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Handler = (msg: Record<string, unknown>) => void;
const handlers = new Map<string, Handler>();

vi.mock("../../../ws/WSProvider", () => ({
  useWS: () => ({
    subscribe: (type: string, handler: Handler) => {
      handlers.set(type, handler);
      return () => handlers.delete(type);
    },
  }),
}));

import {
  Sprite2DRuntime,
  expressionForEmotion,
  type Sprite2DProjection,
} from "../Sprite2DRuntime";
import { _resetCache } from "../preloader";

class FakeImage {
  src = "";
  complete = true;
  onload: (() => void) | null = null;
  onerror: ((event: Event | string) => void) | null = null;
}

const photo = (directive: Sprite2DProjection["directive"]): Sprite2DProjection => ({
  type: "avatar.directive",
  runtime: "sprite2d",
  directive,
  frames: ["http://127.0.0.1:8000/static/characters/ai_girlfriend/idle/000.png"],
  fps: 5,
  loop: true,
});

const cue = (emotion: string) =>
  photo({ state: "happy", emotion, speaking: false, metadata: { source: "llm_structured_output" } });

const folderOf = (container: HTMLElement) =>
  container.querySelector(".avatar")?.getAttribute("data-folder");

const speech = (status: string, id = "u1") =>
  act(() => handlers.get("speech.status")?.({ status, utterance_id: id }));

const originalImage = globalThis.Image;

beforeEach(() => {
  _resetCache();
  handlers.clear();
  globalThis.Image = FakeImage as unknown as typeof Image;
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  globalThis.Image = originalImage;
});

describe("expressionForEmotion", () => {
  it("maps LLM emotions onto the photo folders", () => {
    // Happy keeps the original face: the smile photos look unnatural.
    expect(expressionForEmotion("happy")).toBe("neutral");
    expect(expressionForEmotion("worried")).toBe("sad");
    expect(expressionForEmotion("angry")).toBe("angry");
    expect(expressionForEmotion("surprised")).toBe("surprised");
    expect(expressionForEmotion("confused")).toBe("neutral");
    expect(expressionForEmotion(undefined)).toBe("neutral");
  });
});

describe("Sprite2DRuntime photo expressions", () => {
  it("speaks with the latched expression, holds it, then returns to idle", () => {
    const { container, rerender } = render(
      <Sprite2DRuntime projection={photo({ state: "thinking", emotion: "neutral" })} />,
    );
    expect(folderOf(container)).toBe("idle");

    rerender(<Sprite2DRuntime projection={cue("sad")} />);
    speech("started");
    // Lifecycle directives during speech reset emotion; the latch must win.
    rerender(
      <Sprite2DRuntime projection={photo({ state: "idle", emotion: "neutral", speaking: true })} />,
    );
    expect(folderOf(container)).toBe("sad_speaking");

    rerender(
      <Sprite2DRuntime projection={photo({ state: "idle", emotion: "neutral", speaking: false })} />,
    );
    speech("finished");
    expect(folderOf(container)).toBe("sad");

    act(() => {
      vi.advanceTimersByTime(4100);
    });
    expect(folderOf(container)).toBe("idle");
  });

  it.each(["neutral", "happy"])("uses the original speaking folder for %s replies", (emotion) => {
    const { container, rerender } = render(<Sprite2DRuntime projection={cue(emotion)} />);
    expect(folderOf(container)).toBe("idle");
    speech("started");
    rerender(
      <Sprite2DRuntime projection={photo({ state: "idle", emotion: "neutral", speaking: true })} />,
    );
    expect(folderOf(container)).toBe("speaking");
  });

  it("cross-fades when the expression folder changes", () => {
    const { container, rerender } = render(
      <Sprite2DRuntime projection={photo({ state: "idle", emotion: "neutral" })} />,
    );
    rerender(<Sprite2DRuntime projection={cue("sad")} />);
    expect(container.querySelector(".avatar-frame--fade-out")).not.toBeNull();
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(container.querySelector(".avatar-frame--fade-out")).toBeNull();
  });

  it("a new turn clears a held expression", () => {
    const { container, rerender } = render(<Sprite2DRuntime projection={cue("angry")} />);
    expect(folderOf(container)).toBe("angry");
    rerender(<Sprite2DRuntime projection={photo({ state: "listening", emotion: "neutral" })} />);
    expect(folderOf(container)).toBe("idle");
  });
});
