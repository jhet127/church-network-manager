"""공유기(네트워크)와 통신하는 모듈. 두 가지 모드를 지원한다.

- mode: "scan"    → 공유기를 전혀 건드리지 않고, 같은 네트워크 안에서
                     ARP 테이블을 읽어 "누가 접속해 있는지"만 확인한다.
                     지금 당장 안전하게 쓸 수 있지만, 승인/차단 같은
                     제어 기능은 못 한다 (읽기 전용).
- mode: "openwrt" → 공유기가 OpenWrt로 바뀐 뒤 SSH로 접속해 실제로
                     제어(승인/차단, Wi-Fi on/off, 재부팅)까지 한다.

config.yaml에서 각 공유기 항목의 'mode' 값만 바꾸면 동작 방식이 바뀐다.
코드나 나머지 설정은 그대로 두고 이 값만 바꾸면 되도록 설계했다.
"""
from __future__ import annotations

import logging
import platform
import re
import subprocess
from dataclasses import dataclass

logger = logging.getLogger("router_client")


def _is_multicast_or_broadcast(ip: str) -> bool:
    """224.0.0.0~239.255.255.255(멀티캐스트), x.x.x.255, 255.255.255.255(브로드캐스트) 제외."""
    parts = ip.split(".")
    if len(parts) != 4:
        return True
    first = int(parts[0])
    if 224 <= first <= 239:
        return True
    if parts[3] == "255":
        return True
    return False


@dataclass
class DeviceInfo:
    mac: str
    ip: str
    hostname: str
    is_online: bool


class RouterClient:
    def __init__(self, mode: str = "scan", host: str = "", username: str = "root",
                 password: str | None = None, key_path: str | None = None,
                 port: int = 22, timeout: int = 10, subnet: str | None = None):
        self.mode = mode
        self.host = host
        self.username = username
        self.password = password
        self.key_path = key_path
        self.port = port
        self.timeout = timeout
        self.subnet = subnet  # scan 모드에서 스캔할 대역 (예: "192.168.0.0/24")
        self._ssh = None

    # ------------------------------------------------------------------
    # 연결 관리
    # ------------------------------------------------------------------
    def authorize(self) -> bool:
        if self.mode == "scan":
            return True  # 스캔 모드는 별도 로그인이 필요 없음
        try:
            import paramiko
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            if self.key_path:
                client.connect(self.host, port=self.port, username=self.username,
                                key_filename=self.key_path, timeout=self.timeout)
            else:
                client.connect(self.host, port=self.port, username=self.username,
                                password=self.password, timeout=self.timeout)
            self._ssh = client
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("SSH 연결 실패(%s): %s", self.host, e)
            self._ssh = None
            return False

    def logout(self) -> None:
        if self._ssh:
            try:
                self._ssh.close()
            except Exception:  # noqa: BLE001
                pass
            self._ssh = None

    def _run_ssh(self, command: str) -> str:
        if self._ssh is None:
            raise RuntimeError("SSH 연결이 안 된 상태입니다.")
        _, stdout, stderr = self._ssh.exec_command(command, timeout=self.timeout)
        out = stdout.read().decode("utf-8", errors="ignore")
        err = stderr.read().decode("utf-8", errors="ignore")
        if err.strip():
            logger.debug("명령 '%s' 실행 중 stderr: %s", command, err.strip())
        return out

    # ------------------------------------------------------------------
    # 접속 기기 목록
    # ------------------------------------------------------------------
    def get_connected_devices(self) -> list[DeviceInfo]:
        if self.mode == "scan":
            return self._scan_local_network()
        return self._get_devices_via_ssh()

    def _scan_local_network(self) -> list[DeviceInfo]:
        """공유기에 로그인하지 않고, 이 프로그램이 도는 컴퓨터의 ARP 테이블을 읽는다.
        (같은 네트워크 안의 기기라면 대부분 이 테이블에 최근 통신 기록이 남는다)
        """
        devices: dict[str, DeviceInfo] = {}
        try:
            if platform.system() == "Windows":
                out = subprocess.run(["arp", "-a"], capture_output=True, text=True,
                                      timeout=10).stdout
                for line in out.splitlines():
                    m = re.search(
                        r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]{17})\s+(\S+)", line
                    )
                    if m:
                        ip, mac_raw, _kind = m.groups()
                        # 한글/영어 Windows 모두 "동적"/"dynamic"과 "정적"/"static"으로
                        # 표기가 갈려서, 종류 문자열 대신 IP 형태로 걸러낸다.
                        if _is_multicast_or_broadcast(ip):
                            continue
                        mac = mac_raw.replace("-", ":").upper()
                        devices[mac] = DeviceInfo(mac=mac, ip=ip, hostname="(이름 없음)",
                                                   is_online=True)
            else:
                out = subprocess.run(["ip", "neigh", "show"], capture_output=True,
                                      text=True, timeout=10).stdout
                for line in out.splitlines():
                    m = re.search(
                        r"(\d+\.\d+\.\d+\.\d+).*lladdr\s+([0-9a-fA-F:]+).*"
                        r"(REACHABLE|STALE|DELAY)", line
                    )
                    if m:
                        ip, mac, _ = m.groups()
                        devices[mac.upper()] = DeviceInfo(
                            mac=mac.upper(), ip=ip, hostname="(이름 없음)", is_online=True
                        )
        except Exception as e:  # noqa: BLE001
            logger.error("네트워크 스캔 실패: %s", e)

        # 호스트명은 역방향 DNS 조회로 시도 (실패해도 무시)
        import socket
        for d in devices.values():
            try:
                d.hostname = socket.gethostbyaddr(d.ip)[0]
            except Exception:  # noqa: BLE001
                pass

        return list(devices.values())

    def _get_devices_via_ssh(self) -> list[DeviceInfo]:
        devices: dict[str, DeviceInfo] = {}
        leases_out = self._run_ssh("cat /tmp/dhcp.leases 2>/dev/null")
        for line in leases_out.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            _, mac, ip, hostname = parts[0], parts[1], parts[2], parts[3]
            devices[mac.lower()] = DeviceInfo(
                mac=mac.upper(), ip=ip, hostname=hostname if hostname != "*" else "(이름 없음)",
                is_online=False,
            )
        neigh_out = self._run_ssh("ip neigh show 2>/dev/null")
        online_macs = set()
        for line in neigh_out.splitlines():
            m = re.search(
                r"(\d+\.\d+\.\d+\.\d+).*lladdr\s+([0-9a-fA-F:]+).*(REACHABLE|STALE|DELAY)", line
            )
            if m:
                online_macs.add(m.group(2).lower())
        for mac, d in devices.items():
            d.is_online = mac in online_macs
        return list(devices.values())

    # ------------------------------------------------------------------
    # Wi-Fi / 재부팅 / 승인·차단 - openwrt 모드에서만 실제 동작
    # ------------------------------------------------------------------
    def get_wifi_status(self) -> dict:
        if self.mode == "scan":
            return {}  # 스캔 모드는 조회 불가 (읽기 전용 한계)
        out = self._run_ssh("uci show wireless 2>/dev/null")
        guest_disabled = "wireless.guest.disabled='1'" in out
        guest_on = "wireless.guest=" in out and not guest_disabled
        return {"wifi_2g": True, "wifi_5g": True, "guest_2g": guest_on, "guest_5g": guest_on}

    def set_guest_wifi(self, band: str, enable: bool) -> None:
        if self.mode == "scan":
            raise NotImplementedError("스캔 모드에서는 Wi-Fi 제어가 불가능합니다 (읽기 전용).")
        value = "0" if enable else "1"
        self._run_ssh(f"uci set wireless.guest.disabled='{value}' && uci commit wireless && wifi reload")

    def reboot(self) -> None:
        if self.mode == "scan":
            raise NotImplementedError("스캔 모드에서는 재부팅 제어가 불가능합니다 (읽기 전용).")
        self._run_ssh("reboot &")

    def approve_device(self, mac: str) -> None:
        if self.mode == "scan":
            logger.info("스캔 모드 - 승인은 기록만 되고 실제 차단/허용은 적용되지 않습니다.")
            return
        self._run_ssh(f"nft add element inet fw4 approved_macs {{ {mac.lower()} }} 2>/dev/null")

    def unapprove_device(self, mac: str) -> None:
        if self.mode == "scan":
            logger.info("스캔 모드 - 미승인은 기록만 되고 실제 차단/허용은 적용되지 않습니다.")
            return
        self._run_ssh(f"nft delete element inet fw4 approved_macs {{ {mac.lower()} }} 2>/dev/null")

    def list_approved_macs(self) -> list[str]:
        if self.mode == "scan":
            return []
        out = self._run_ssh("nft list set inet fw4 approved_macs 2>/dev/null")
        m = re.search(r"elements\s*=\s*\{([^}]*)\}", out)
        if not m:
            return []
        return [x.strip().upper() for x in m.group(1).split(",") if x.strip()]
