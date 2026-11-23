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
  it("shows Benny by default and 叮當's standing/laughing pictures after a switch", () => {
    const { rerender } = render(<Sprite2DRuntime projection={photo(false)} />);
    expect(src()).toContain("/ai_girlfriend/idle/");

    act(() => handlers.get("character.active")?.({ type: "character.active", id: "dingdong" }));
    expect(src()).toBe("http://127.0.0.1:8000/static/characters/dingdong/idle.png");

    rerender(<Sprite2DRuntime projection={photo(true)} />);
    expect(src()).toBe("http://127.0.0.1:8000/static/characters/dingdong/speaking.png");

    act(() => handlers.get("character.active")?.({ type: "character.active", id: "benny" }));
    expect(src()).toContain("/ai_girlfriend/speaking/");
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
