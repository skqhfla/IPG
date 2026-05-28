"""
UID 단위 패킷/바이트 누적치 snapshot.

`adb shell dumpsys netstats detail full` 출력을 파싱해 target UID의
tx/rx packets/bytes 누적값을 얻는다. 이벤트 직전/직후 snapshot의 차분으로
"이 이벤트가 유발한 트래픽"을 측정한다.

루트·추가 APK 불필요. UID는 `dumpsys package <pkg>`의 `userId=N` 라인에서 해석.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from core.adb.device import ADBDevice


_PM_LIST_UID_RE = re.compile(r"\buid:(\d+)\b")
_PKG_DUMP_UID_RE = re.compile(r"\b(?:userId|appId)=(\d+)")
_UID_RE = re.compile(r"\buid=(-?\d+)\b")
_TAG_ZERO_RE = re.compile(r"\btag=0x0\b")
# dumpsys netstats detail full 의 NetworkStatsHistory 버킷 라인:
# `st=<ts> rb=<rxBytes> rp=<rxPackets> tb=<txBytes> tp=<txPackets> op=<ops>`
_BUCKET_RE = re.compile(
    r"\brb=(\d+)\s+rp=(\d+)\s+tb=(\d+)\s+tp=(\d+)\b"
)


@dataclass(frozen=True, slots=True)
class PacketStat:
    tx_packets: int = 0
    rx_packets: int = 0
    tx_bytes: int = 0
    rx_bytes: int = 0

    def total_packets(self) -> int:
        return self.tx_packets + self.rx_packets

    def total_bytes(self) -> int:
        return self.tx_bytes + self.rx_bytes

    def delta(self, before: "PacketStat") -> "PacketStat":
        # 누적값이므로 항상 self >= before 여야 하지만, 카운터 리셋·UID 재할당
        # 등 비정상 상황을 흡수하기 위해 음수는 0으로 clamp.
        return PacketStat(
            tx_packets=max(0, self.tx_packets - before.tx_packets),
            rx_packets=max(0, self.rx_packets - before.rx_packets),
            tx_bytes=max(0, self.tx_bytes - before.tx_bytes),
            rx_bytes=max(0, self.rx_bytes - before.rx_bytes),
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "tx_packets": self.tx_packets,
            "rx_packets": self.rx_packets,
            "tx_bytes": self.tx_bytes,
            "rx_bytes": self.rx_bytes,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PacketStat":
        return cls(
            tx_packets=int(d.get("tx_packets", 0)),
            rx_packets=int(d.get("rx_packets", 0)),
            tx_bytes=int(d.get("tx_bytes", 0)),
            rx_bytes=int(d.get("rx_bytes", 0)),
        )


def resolve_uid(device: ADBDevice, package: str) -> Optional[int]:
    # 1차: pm list packages -U <pkg> — Android 9+ 표준, 정확히 한 줄
    #      "package:<pkg> uid:<N>" 형태로 반환.
    try:
        output = device.shell_text(
            f"pm list packages -U {package}",
            timeout=10.0,
            check=False,
        )
    except Exception:
        output = ""

    for line in output.splitlines():
        # 같은 prefix를 가진 다른 패키지가 끼지 않도록 정확 매칭.
        if f"package:{package} " in line or line.startswith(f"package:{package} "):
            m = _PM_LIST_UID_RE.search(line)
            if m is not None:
                return int(m.group(1))

    # 2차 fallback: dumpsys package <pkg> — 신형(Android 11+)은 appId=,
    # 구형은 userId= 로 출력.
    try:
        output = device.shell_text(
            f"dumpsys package {package}",
            timeout=15.0,
            check=False,
        )
    except Exception:
        return None

    m = _PKG_DUMP_UID_RE.search(output)
    if m is None:
        return None
    return int(m.group(1))


class NetstatsSampler:
    def __init__(
        self,
        *,
        device: ADBDevice,
        uid: int,
        logger: Any = None,
    ) -> None:
        self.device = device
        self.uid = uid
        self.logger = logger

    def sample(self) -> Optional[PacketStat]:
        # 실패 시 None을 반환해 호출자가 baseline 누락에 따른 거짓 큰 delta를
        # 만들지 않게 한다. UID 매칭 라인이 0개여도 parser는 PacketStat()를
        # 돌려주는데, 이는 "트래픽 없음"을 의미하는 정상 zero baseline이다.
        try:
            output = self.device.shell_text(
                "dumpsys netstats detail full",
                timeout=20.0,
                check=False,
            )
        except Exception as e:
            if self.logger:
                self.logger.warning(f"[NETSTATS] dumpsys 실패: {e}")
            return None

        return _parse_uid_total(output, self.uid)


def _parse_uid_total(output: str, target_uid: int) -> PacketStat:
    # `dumpsys netstats detail full` 출력 구조:
    #   ident=[...] uid=<U> set=<S> tag=<T>            <- 블록 헤더
    #     NetworkStatsHistory: bucketDuration=...
    #       st=<ts> rb=<rxBytes> rp=<rxPackets> tb=<txBytes> tp=<txPackets> op=<ops>
    #       st=...                                     <- 시계열 버킷
    #
    # target UID의 누적 트래픽 = 모든 (iface, set) 블록 중 tag=0x0 인 헤더 아래
    # 모든 버킷의 rb/rp/tb/tp 합. tag!=0x0(UID tag stats) 블록은 하위 분류라
    # 합치면 중복되므로 제외한다. uid=-1 등 다른 UID 헤더가 나오면 합산 중단.
    tx_p = rx_p = tx_b = rx_b = 0
    in_target_block = False

    for line in output.splitlines():
        m_uid = _UID_RE.search(line)
        if m_uid is not None:
            # uid=N 토큰을 본 라인은 항상 블록 헤더로 간주 — target_uid + tag=0x0
            # 일 때만 누적 활성화.
            in_target_block = (
                int(m_uid.group(1)) == target_uid
                and _TAG_ZERO_RE.search(line) is not None
            )
            continue

        if not in_target_block:
            continue

        m = _BUCKET_RE.search(line)
        if m is not None:
            rx_b += int(m.group(1))
            rx_p += int(m.group(2))
            tx_b += int(m.group(3))
            tx_p += int(m.group(4))

    return PacketStat(
        tx_packets=tx_p,
        rx_packets=rx_p,
        tx_bytes=tx_b,
        rx_bytes=rx_b,
    )
