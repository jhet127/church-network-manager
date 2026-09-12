"""라즈베리파이에서 Firebase(Firestore)로 데이터를 올리고,
휴대폰 앱이 남긴 명령을 받아오는 모듈.

동작 방식:
- 라즈베리파이가 공유기를 폴링할 때마다 기기 목록/Wi-Fi 상태를 Firestore에 씀 (앱은 읽기만)
- 휴대폰 앱은 'commands' 컬렉션에 문서를 추가해 명령을 남김
- 라즈베리파이가 주기적으로 'commands'에서 status == 'pending' 문서를 읽어 실행하고,
  처리 후 status를 'done' 또는 'error'로 바꿈

사전 준비: Firebase 콘솔 > 프로젝트 설정 > 서비스 계정 > "새 비공개 키 생성"으로
받은 JSON 파일을 라즈베리파이의 `serviceAccountKey.json`으로 저장하세요.
이 파일은 절대 GitHub에 올리면 안 됩니다 (.gitignore에 이미 포함되어 있음).
"""
from __future__ import annotations

import logging

logger = logging.getLogger("firebase_sync")

_db = None


def init(service_account_path: str):
    """Firestore 클라이언트를 초기화한다. 실패해도 앱 전체가 죽지 않도록 예외를 삼킨다."""
    global _db
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore

        if not firebase_admin._apps:
            cred = credentials.Certificate(service_account_path)
            firebase_admin.initialize_app(cred)
        _db = firestore.client()
        logger.info("Firebase 연동 초기화 완료")
    except Exception as e:  # noqa: BLE001
        logger.error("Firebase 초기화 실패(로컬 기능은 계속 동작함): %s", e)
        _db = None


def is_ready() -> bool:
    return _db is not None


def push_devices(devices: list[dict]) -> None:
    if _db is None:
        return
    try:
        batch = _db.batch()
        for d in devices:
            ref = _db.collection("devices").document(d["mac"])
            batch.set(ref, {
                "router_id": d.get("router_id", ""),
                "ip": d.get("ip", ""),
                "hostname": d.get("hostname", ""),
                "alias": d.get("alias", ""),
                "is_online": bool(d.get("is_online")),
                "approved": bool(d.get("approved")),
                "latency_ms": d.get("latency_ms"),
                "last_seen": d.get("last_seen"),
            }, merge=True)
        batch.commit()
    except Exception as e:  # noqa: BLE001
        logger.error("기기 목록 업로드 실패: %s", e)


def push_wifi_status(status: dict) -> None:
    if _db is None:
        return
    try:
        _db.collection("wifi_status").document("current").set(status, merge=True)
    except Exception as e:  # noqa: BLE001
        logger.error("Wi-Fi 상태 업로드 실패: %s", e)


def push_routers(routers: list[dict]) -> None:
    if _db is None:
        return
    try:
        batch = _db.batch()
        for r in routers:
            ref = _db.collection("routers").document(r["id"])
            batch.set(ref, {"label": r["label"]}, merge=True)
        batch.commit()
    except Exception as e:  # noqa: BLE001
        logger.error("공유기 목록 업로드 실패: %s", e)


def push_event(mac: str, event: str, hostname: str, ts: int) -> None:
    if _db is None:
        return
    try:
        _db.collection("events").add({
            "mac": mac, "event": event, "hostname": hostname, "ts": ts,
        })
    except Exception as e:  # noqa: BLE001
        logger.error("이벤트 업로드 실패: %s", e)


def push_event(mac: str, event: str, hostname: str, ts: int) -> None:
    if _db is None:
        return
    try:
        _db.collection("events").add({
            "mac": mac, "event": event, "hostname": hostname, "ts": ts,
        })
    except Exception as e:  # noqa: BLE001
        logger.error("이벤트 업로드 실패: %s", e)


def sync_accounts() -> None:
    """Firebase Authentication의 계정 목록 + 현재 권한을 Firestore 'accounts'에 올린다.

    앱은 이 컬렉션을 읽기만 해서 계정 관리 화면에 표시한다.
    (계정 목록 조회는 firebase-admin 권한이 있어야만 가능해서, 이 작업은
    라즈베리파이만 할 수 있다.)
    """
    if _db is None:
        return
    try:
        from firebase_admin import auth as fb_auth

        role_docs = {d.id: d.to_dict().get("role") for d in _db.collection("users").stream()}
        batch = _db.batch()
        page = fb_auth.list_users()
        for user in page.iterate_all():
            ref = _db.collection("accounts").document(user.uid)
            batch.set(ref, {
                "email": user.email or "(이메일 없음)",
                "role": "admin" if role_docs.get(user.uid) == "admin" else "viewer",
            })
        batch.commit()
    except Exception as e:  # noqa: BLE001
        logger.error("계정 목록 동기화 실패: %s", e)


def set_account_role(uid: str, make_admin: bool) -> None:
    """특정 계정을 관리자로 만들거나(관리자 문서 생성), 뷰어로 되돌린다(문서 삭제)."""
    if _db is None:
        return
    ref = _db.collection("users").document(uid)
    if make_admin:
        ref.set({"role": "admin"})
    else:
        ref.delete()


def fetch_pending_commands() -> list[dict]:
    """앱이 남긴 처리 대기 중인 명령들을 가져온다."""
    if _db is None:
        return []
    try:
        docs = _db.collection("commands").where("status", "==", "pending").stream()
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception as e:  # noqa: BLE001
        logger.error("명령 조회 실패: %s", e)
        return []


def mark_command_done(command_id: str, ok: bool, message: str = "") -> None:
    if _db is None:
        return
    try:
        _db.collection("commands").document(command_id).update({
            "status": "done" if ok else "error", "result": message,
        })
    except Exception as e:  # noqa: BLE001
        logger.error("명령 상태 갱신 실패: %s", e)
