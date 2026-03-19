from __future__ import annotations

from core.adb.device import ADBDevice
from core.app_types.run_meta import AppMeta, DeviceMeta


def collect_device_meta(adb_device: ADBDevice) -> DeviceMeta:
    screen_width, screen_height = adb_device.get_screen_size()

    return DeviceMeta(
        model=adb_device.get_prop("ro.product.model"),
        manufacturer=adb_device.get_prop("ro.product.manufacturer"),
        version=adb_device.get_prop("ro.build.version.release"),
        sdk=adb_device.get_prop("ro.build.version.sdk"),
        serial=adb_device.get_prop("ro.serialno"),
        screen_width=screen_width,
        screen_height=screen_height,
    )


def collect_app_meta(
    adb_device: ADBDevice,
    *,
    app_name: str,
    package: str,
) -> AppMeta:
    dumpsys = adb_device.get_package_info_text(package)

    version = _find_after_prefix(dumpsys, "versionName=")
    version_code_raw = _find_after_prefix(dumpsys, "versionCode=")
    version_code = version_code_raw.split()[0] if version_code_raw else ""

    uid = _find_after_prefix(dumpsys, "userId=")
    last_update = _find_after_prefix(dumpsys, "lastUpdateTime=")

    return AppMeta(
        app_name=app_name,
        package=package,
        version=version or "",
        version_code=version_code or "",
        uid=uid,
        last_update=last_update,
    )


def _find_after_prefix(text: str, prefix: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip()
    return None