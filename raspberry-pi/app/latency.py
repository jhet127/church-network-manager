"""기기의 응답 지연시간(ping)을 측정하는 모듈.

라즈베리파이(리눅스)와 Windows에서 ping 명령의 옵션 형식이 서로 달라서
운영체제를 확인해 알맞은 옵션을 사용한다.
"""
from __future__ import annotations

import platform
import re
import subprocess


def ping_ms(ip: str, timeout_sec: float = 1.0) -> int | None:
    """해당 IP로 ping 1회를 보내 왕복 시간(ms)을 반환한다. 실패하면 None."""
    if not ip:
        return None
    try:
        if platform.system() == "Windows":
            # Windows: -n(횟수), -w(타임아웃, ms 단위)
            cmd = ["ping", "-n", "1", "-w", str(int(timeout_sec * 1000)), ip]
        else:
            # 리눅스/맥: -c(횟수), -W(타임아웃, 초 단위)
            cmd = ["ping", "-c", "1", "-W", str(int(timeout_sec)), ip]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_sec + 2,
        )
        if result.returncode != 0:
            return None
        match = re.search(r"time[=<]\s*([\d.]+)", result.stdout)
        return round(float(match.group(1))) if match else None
    except Exception:  # noqa: BLE001
        return None
