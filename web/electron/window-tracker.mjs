// Owns the app's single main window without ever handing out a destroyed one.
//
// On macOS, closing the last window keeps the app running. The BrowserWindow
// behind it is destroyed, so any later call on that object (for example from
// the dock-click "activate" event) throws "Object has been destroyed" and
// crashes the main process. The tracker drops its reference on "closed" and
// recreates the window from the last URL when the app is activated again.
export function createWindowTracker({ createWindow, getAllWindows }) {
  let tracked = null;
  let lastUrl = null;

  function current() {
    return tracked && !tracked.isDestroyed() ? tracked : null;
  }

  function open(url) {
    lastUrl = url;
    const win = createWindow(url);
    tracked = win;
    win.on("closed", () => {
      if (tracked === win) tracked = null;
    });
    return win;
  }

  function activate() {
    if (current()) return;
    if (getAllWindows().length > 0) return;
    if (lastUrl) open(lastUrl);
  }

  function focus() {
    const win = current();
    if (!win) return;
    if (win.isMinimized()) win.restore();
    win.focus();
  }

  return { open, current, activate, focus };
}
