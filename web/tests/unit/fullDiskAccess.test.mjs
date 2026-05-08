import { describe, expect, it } from "vitest";

import {
  FULL_DISK_ACCESS_SETTINGS_URL,
  fullDiskAccessDialogOptions,
} from "../../electron/full-disk-access.mjs";

describe("full disk access guidance", () => {
  it("points macOS users at the Full Disk Access settings pane", () => {
    expect(FULL_DISK_ACCESS_SETTINGS_URL).toContain("Privacy_AllFiles");
  });

  it("explains why the desktop app needs the permission", () => {
    const options = fullDiskAccessDialogOptions("DevDoctor");

    expect(options.message).toContain("DevDoctor");
    expect(options.detail).toContain("Privacy & Security > Full Disk Access");
    expect(options.detail).toContain("disk scans may miss protected folders");
    expect(options.buttons[0]).toBe("Open System Settings");
  });
});
