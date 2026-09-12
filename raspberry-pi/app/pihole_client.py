"""Pi-hole(라즈베리파이에 함께 설치하는 DNS 필터링 서버)과 통신하는 모듈.

네트워크 전체(모든 실, 모든 기기)에서 특정 사이트를 막으려면
메인 공유기의 DHCP가 나눠주는 DNS 서버 주소를 이 라즈베리파이로 향하게 해야 합니다.
(README "사이트 차단 - Pi-hole 설정" 절 참고)

Pi-hole 6.x REST API를 사용합니다. 공식 문서: https://docs.pi-hole.net/api/
"""
from __future__ import annotations

import logging

import requests

logger = logging.getLogger("pihole_client")


class PiholeClient:
    def __init__(self, base_url: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.password = password
        self._session_id: str | None = None

    def _login(self) -> bool:
        try:
            resp = requests.post(
                f"{self.base_url}/api/auth", json={"password": self.password}, timeout=5
            )
            resp.raise_for_status()
            self._session_id = resp.json()["session"]["sid"]
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("Pi-hole 로그인 실패: %s", e)
            self._session_id = None
            return False

    def _headers(self) -> dict:
        return {"sid": self._session_id} if self._session_id else {}

    def list_blocked_domains(self) -> list[str]:
        if not self._session_id and not self._login():
            return []
        try:
            resp = requests.get(
                f"{self.base_url}/api/domains/deny/exact",
                headers=self._headers(),
                timeout=5,
            )
            resp.raise_for_status()
            return [d["domain"] for d in resp.json().get("domains", [])]
        except Exception as e:  # noqa: BLE001
            logger.error("차단 목록 조회 실패: %s", e)
            return []

    def block_domain(self, domain: str) -> bool:
        if not self._session_id and not self._login():
            return False
        try:
            resp = requests.post(
                f"{self.base_url}/api/domains/deny/exact",
                headers=self._headers(),
                json={"domain": domain, "comment": "교회 네트워크 관리 시스템에서 추가"},
                timeout=5,
            )
            resp.raise_for_status()
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("사이트 차단 실패(%s): %s", domain, e)
            return False

    def unblock_domain(self, domain: str) -> bool:
        if not self._session_id and not self._login():
            return False
        try:
            resp = requests.delete(
                f"{self.base_url}/api/domains/deny/exact/{domain}",
                headers=self._headers(),
                timeout=5,
            )
            resp.raise_for_status()
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("사이트 차단 해제 실패(%s): %s", domain, e)
            return False

    def get_status(self) -> dict | None:
        if not self._session_id and not self._login():
            return None
        try:
            resp = requests.get(
                f"{self.base_url}/api/dns/blocking", headers=self._headers(), timeout=5
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:  # noqa: BLE001
            logger.error("Pi-hole 상태 조회 실패: %s", e)
            return None
