from __future__ import annotations

import json
import os
from pathlib import Path

from devdoctor.providers.base import Provider
from devdoctor.providers.tool_caches import _path_entry
from devdoctor.types import AdviceAction, CommandAction, DeletePathAction, Entry, Risk


class XcodeProvider(Provider):
    name = "xcode-development-data"
    family = "xcode"
    description = "Xcode derived data, device support, archives, and unavailable simulators"
    platforms = ("darwin",)
    risk = Risk.RECLAIMABLE
    details = (
        "DerivedData and old DeviceSupport are rebuildable. Archives and simulator "
        "user data remain dangerous/advice-only; unavailable simulators use simctl."
    )

    def discover(self) -> list[Entry]:
        entries: list[Entry] = []
        developer = Path("~/Library/Developer/Xcode").expanduser()
        for root_name, label_prefix in (
            ("DerivedData", "Xcode DerivedData"),
            ("iOS DeviceSupport", "iOS DeviceSupport"),
        ):
            root = developer / root_name
            if not root.is_dir():
                continue
            for child in sorted(root.iterdir()):
                if not child.is_dir():
                    continue
                entry = _path_entry(
                    self,
                    child,
                    id_=str(child),
                    label=f"{label_prefix}: {child.name}",
                    risk=Risk.RECLAIMABLE,
                    actions=(DeletePathAction(child),),
                    reclaimable=True,
                )
                if entry is not None:
                    entries.append(entry)

        archives = developer / "Archives"
        if archives.is_dir():
            for archive in sorted(archives.glob("*/*.xcarchive")):
                entry = _path_entry(
                    self,
                    archive,
                    id_=str(archive),
                    label=f"Xcode archive: {archive.stem}",
                    risk=Risk.DANGEROUS,
                    actions=(
                        AdviceAction(
                            f"{archive} may be the only retained signed build. Export or "
                            "verify it in Xcode Organizer before deleting it."
                        ),
                    ),
                    reclaimable=None,
                )
                if entry is not None:
                    entries.append(entry)

        entries.extend(self._unavailable_simulators())
        return entries

    def _unavailable_simulators(self) -> list[Entry]:
        if self._shell.which("xcrun") is None:
            return []
        result = self._shell.run(
            ["xcrun", "simctl", "list", "devices", "unavailable", "-j"],
            check=False,
        )
        if result.returncode != 0:
            self.diagnostics.append("xcode-development-data: simctl device listing failed")
            return []
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            self.diagnostics.append("xcode-development-data: simctl returned invalid JSON")
            return []
        devices = payload.get("devices") if isinstance(payload, dict) else None
        if not isinstance(devices, dict):
            return []
        entries: list[Entry] = []
        for rows in devices.values():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict) or row.get("isAvailable") is True:
                    continue
                udid = row.get("udid")
                data_path = row.get("dataPath")
                if not isinstance(udid, str):
                    continue
                path = (
                    Path(data_path)
                    if isinstance(data_path, str)
                    else Path("~/Library/Developer/CoreSimulator/Devices").expanduser() / udid
                )
                name = row.get("name")
                entry = _path_entry(
                    self,
                    path,
                    id_=f"simulator:{udid}",
                    label=f"Unavailable simulator: {name or udid}",
                    risk=Risk.RECLAIMABLE,
                    actions=(CommandAction(("xcrun", "simctl", "delete", udid)),),
                    reclaimable=True,
                )
                if entry is not None:
                    entries.append(entry)
        return entries


class AndroidSdkProvider(Provider):
    name = "android-sdk-storage"
    family = "android"
    description = "Android SDK system images and emulator device storage"
    platforms = ("darwin", "linux")
    risk = Risk.RECLAIMABLE
    details = (
        "SDK system images use sdkmanager when available. AVD storage contains "
        "mutable emulator data and is therefore advice-only."
    )

    def discover(self) -> list[Entry]:
        entries = self._system_images()
        entries.extend(self._avds())
        return entries

    def _sdk_root(self) -> Path | None:
        configured = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
        candidates = (
            Path(configured).expanduser() if configured else None,
            Path("~/Library/Android/sdk").expanduser(),
            Path("~/Android/Sdk").expanduser(),
        )
        return next((path for path in candidates if path is not None and path.is_dir()), None)

    def _sdkmanager(self, root: Path) -> str | None:
        from_path = self._shell.which("sdkmanager")
        if from_path:
            return from_path
        candidates = (
            root / "cmdline-tools" / "latest" / "bin" / "sdkmanager",
            root / "tools" / "bin" / "sdkmanager",
        )
        return next((str(path) for path in candidates if path.is_file()), None)

    def _system_images(self) -> list[Entry]:
        root = self._sdk_root()
        if root is None:
            return []
        images = root / "system-images"
        if not images.is_dir():
            return []
        sdkmanager = self._sdkmanager(root)
        entries: list[Entry] = []
        for package_file in images.glob("*/*/*/package.xml"):
            path = package_file.parent
            package_id = ";".join(path.relative_to(root).parts)
            action = (
                CommandAction((sdkmanager, "--uninstall", package_id))
                if sdkmanager is not None
                else AdviceAction(
                    f"Remove Android SDK package {package_id} with SDK Manager; "
                    f"sdkmanager was not found for {root}."
                )
            )
            entry = _path_entry(
                self,
                path,
                id_=package_id,
                label=package_id,
                risk=Risk.RECLAIMABLE if sdkmanager is not None else Risk.DANGEROUS,
                actions=(action,),
                reclaimable=True if sdkmanager is not None else None,
            )
            if entry is not None:
                entries.append(entry)
        return entries

    def _avds(self) -> list[Entry]:
        avd_root = Path(os.path.expanduser(os.environ.get("ANDROID_AVD_HOME", "~/.android/avd")))
        if not avd_root.is_dir():
            return []
        entries: list[Entry] = []
        for path in sorted(avd_root.glob("*.avd")):
            entry = _path_entry(
                self,
                path,
                id_=str(path),
                label=f"Android virtual device: {path.stem}",
                risk=Risk.DANGEROUS,
                actions=(
                    AdviceAction(
                        f"{path} contains mutable emulator application data. Delete the "
                        "AVD through Android Studio Device Manager after reviewing it."
                    ),
                ),
                reclaimable=None,
            )
            if entry is not None:
                entries.append(entry)
        return entries
