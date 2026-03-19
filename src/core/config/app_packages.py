from __future__ import annotations

APP_PACKAGES: dict[str, str] = {
    "BN-LINK": "com.BN_LINKsmart.smart",
    "LG": "com.leghe.nuts",
    "Xiaomi": "com.xiaomi.smarthome",
    "Hue": "com.philips.lighting.hue2",
    "cam720": "com.jooan.qiaoanzhilian.fmr.gp",
    "Tapo": "com.tplink.iot",
    "SmartThings": "com.samsung.android.oneconnect",
    "Sengled": "com.sengled.life2",
    "Kasa": "com.tplink.kasa_android",
    "Hejhome": "com.goqual",
}


def get_app_package(app_name: str) -> str:
    key = (app_name or "").strip()

    if not key:
        raise KeyError("App name is empty.")

    try:
        return APP_PACKAGES[key]
    except KeyError:
        known = ", ".join(sorted(APP_PACKAGES.keys()))
        raise KeyError(
            f"Unknown app '{key}'. Known apps: {known}"
        )


def list_supported_apps() -> list[str]:
    return sorted(APP_PACKAGES.keys())