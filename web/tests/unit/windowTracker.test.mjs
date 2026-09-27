import { EventEmitter } from "node:events";

import { describe, expect, it, vi } from "vitest";

import { createWindowTracker } from "../../electron/window-tracker.mjs";

// Mimics the part of BrowserWindow the tracker relies on: once closed, every
// method throws the way Electron does on a destroyed native object.
class FakeWindow extends EventEmitter {
  destroyed = false;
  minimized = false;
  focused = false;

  isDestroyed() {
    return this.destroyed;
  }

  close() {
    this.destroyed = true;
    this.emit("closed");
  }

  show() {
    this.#assertAlive();
  }

  focus() {
    this.#assertAlive();
    this.focused = true;
  }

  isMinimized() {
    this.#assertAlive();
    return this.minimized;
  }

  restore() {
    this.#assertAlive();
    this.minimized = false;
  }

  #assertAlive() {
    if (this.destroyed) throw new TypeError("Object has been destroyed");
  }
}

function setup() {
  const created = [];
  const createWindow = vi.fn((url) => {
    const win = new FakeWindow();
    created.push({ url, win });
    return win;
  });
  const getAllWindows = () => created.map(({ win }) => win).filter((win) => !win.isDestroyed());
  const tracker = createWindowTracker({ createWindow, getAllWindows });
  return { tracker, createWindow, created };
}

describe("window tracker", () => {
  it("recreates the window on activate after the user closed it", () => {
    const { tracker, createWindow, created } = setup();
    tracker.open("http://127.0.0.1:1234");
    created[0].win.close();

    expect(() => tracker.activate()).not.toThrow();

    expect(createWindow).toHaveBeenCalledTimes(2);
    expect(created[1].url).toBe("http://127.0.0.1:1234");
    expect(tracker.current()).toBe(created[1].win);
  });

  it("leaves an open window alone on activate", () => {
    const { tracker, createWindow, created } = setup();
    tracker.open("http://127.0.0.1:1234");

    tracker.activate();

    expect(createWindow).toHaveBeenCalledTimes(1);
    expect(tracker.current()).toBe(created[0].win);
  });

  it("does nothing on activate before the app has a URL to show", () => {
    const { tracker, createWindow } = setup();

    tracker.activate();

    expect(createWindow).not.toHaveBeenCalled();
    expect(tracker.current()).toBeNull();
  });

  it("never hands out a destroyed window", () => {
    const { tracker, created } = setup();
    tracker.open("http://127.0.0.1:1234");
    created[0].win.close();

    expect(tracker.current()).toBeNull();
  });

  it("focuses and restores the live window on second-instance, and ignores a closed one", () => {
    const { tracker, created } = setup();
    tracker.open("http://127.0.0.1:1234");
    created[0].win.minimized = true;

    tracker.focus();
    expect(created[0].win.minimized).toBe(false);
    expect(created[0].win.focused).toBe(true);

    created[0].win.close();
    expect(() => tracker.focus()).not.toThrow();
  });
});
