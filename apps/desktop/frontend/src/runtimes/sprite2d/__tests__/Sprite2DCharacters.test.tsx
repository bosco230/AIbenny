import { act, cleanup, render, renderHook, screen } from "@testing-library/react";
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

import { Sprite2DRuntime, type Sprite2DProjection } from "../Sprite2DRuntime";
import { _resetCache } from "../preloader";
import { useCharacterSwitchKey } from "../../../hooks/useCharacterSwitchKey";

class FakeImage {
  src = "";
  complete = true;
  onload: (() => void) | null = null;
  onerror: ((event: Event | string) => void) | null = null;
}

const photo = (speaking: boolean): Sprite2DProjection => ({
  type: "avatar.directive",
  runtime: "sprite2d",
  directive: { state: "idle", emotion: "neutral", speaking },
  frames: ["http://127.0.0.1:8000/static/characters/ai_girlfriend/idle/000.png"],
  fps: 5,
  loop: true,
});

const src = () => (screen.getByRole("img") as HTMLImageElement).getAttribute("src");

const originalImage = globalThis.Image;

beforeEach(() => {
  _resetCache();
  handlers.clear();
  globalThis.Image = FakeImage as unknown as typeof Image;
});

afterEach(() => {
  cleanup();
  globalThis.Image = originalImage;
  vi.restoreAllMocks();
});

describe("character switching", () => {
  it("shows Benny by default and 叮當's screen-face robot after a switch", () => {
    const { rerender } = render(<Sprite2DRuntime projection={photo(false)} />);
    expect(src()).toContain("/ai_girlfriend/idle/");

    act(() => handlers.get("character.active")?.({ type: "character.active", id: "dingdong" }));
    expect(src()).toBe("http://127.0.0.1:8000/static/characters/dingdong/faces/neutral/000.svg");

    rerender(<Sprite2DRuntime projection={photo(true)} />);
    expect(src()).toMatch(/dingdong\/faces\/neutral\/00[0-3]\.svg$/);

    act(() => handlers.get("character.active")?.({ type: "character.active", id: "benny" }));
    expect(src()).toContain("/ai_girlfriend/speaking/");
  });

  it("叮當 smiles, laughs, cries and relaxes back to neutral", () => {
    vi.useFakeTimers();
    const cue = (emotion: string, intensity: number): Sprite2DProjection => ({
      ...photo(false),
      directive: { state: "happy", emotion, intensity, metadata: { source: "llm_structured_output" } },
    });
    const face = () => document.querySelector(".avatar--dingdong")?.getAttribute("data-face");
    const { rerender } = render(<Sprite2DRuntime projection={photo(false)} />);
    act(() => handlers.get("character.active")?.({ type: "character.active", id: "dingdong" }));

    rerender(<Sprite2DRuntime projection={cue("happy", 0.3)} />);
    expect(face()).toBe("smile");
    rerender(<Sprite2DRuntime projection={cue("happy", 0.9)} />);
    expect(face()).toBe("happy");

    // Sad reply spoken aloud: sad while talking, held after, then neutral.
    rerender(<Sprite2DRuntime projection={cue("sad", 0.7)} />);
    rerender(<Sprite2DRuntime projection={photo(true)} />);
    expect(face()).toBe("sad");
    expect(src()).toMatch(/faces\/sad\/00[0-3]\.svg$/);
    rerender(<Sprite2DRuntime projection={photo(false)} />);
    expect(face()).toBe("sad");
    act(() => {
      vi.advanceTimersByTime(4100);
    });
    expect(face()).toBe("neutral");

    rerender(
      <Sprite2DRuntime projection={{ ...photo(false), directive: { state: "thinking", emotion: "neutral" } }} />,
    );
    expect(face()).toBe("thinking");
    vi.useRealTimers();
  });

  it("gives 叮當 idle/talking motion classes and leaves Benny plain", () => {
    const { container, rerender } = render(<Sprite2DRuntime projection={photo(false)} />);
    expect(container.querySelector(".avatar--dingdong")).toBeNull();

    act(() => handlers.get("character.active")?.({ type: "character.active", id: "dingdong" }));
    const idle = container.querySelector(".avatar--dingdong");
    expect(idle?.classList.contains("avatar--dd-idle")).toBe(true);
    expect(container.querySelector(".dd-motion .dd-pop .dd-frame")).not.toBeNull();

    rerender(<Sprite2DRuntime projection={photo(true)} />);
    const talking = container.querySelector(".avatar--dingdong") as HTMLElement;
    expect(talking.classList.contains("avatar--dd-speaking")).toBe(true);
    // Without RMS data the natural talking loop opens the mouth (level 0-3).
    expect(["0", "1", "2", "3"]).toContain(talking.style.getPropertyValue("--dd-level"));
  });

  it("Escape posts /characters/next once; modified Escape is ignored", () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response("{}")));
    vi.stubGlobal("fetch", fetchMock);
    renderHook(() => useCharacterSwitchKey());

    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", ctrlKey: true }));
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "a" }));
    });
    expect(fetchMock).not.toHaveBeenCalled();

    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(fetchMock).toHaveBeenCalledWith("/characters/next", { method: "POST" });
    vi.unstubAllGlobals();
  });
});
