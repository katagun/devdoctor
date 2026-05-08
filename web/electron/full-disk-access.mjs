export const FULL_DISK_ACCESS_SETTINGS_URL =
  "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles";

export function fullDiskAccessDialogOptions(appName = "DevDoctor") {
  return {
    type: "info",
    title: "Full Disk Access",
    message: `${appName} may need Full Disk Access to scan protected folders.`,
    detail:
      `Open System Settings, enable ${appName} under Privacy & Security > Full Disk Access, ` +
      `then restart ${appName}. Without this permission, disk scans may miss protected folders ` +
      "such as Mail, Messages, browser profiles, and some application data.",
    buttons: ["Open System Settings", "OK"],
    defaultId: 0,
    cancelId: 1,
  };
}
