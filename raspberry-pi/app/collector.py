"""공유기(여러 대)를 주기적으로 확인해서 DB에 기록하고, Firebase가 설정되어 있으면
Firestore에도 올리고, 휴대폰 앱이 남긴 명령을 실행한다.
"""
from __future__ import annotations

import logging
import time

from . import firebase_sync
from .db import Database
from .latency import ping_ms
from .pihole_client import PiholeClient
from .router_client import RouterClient

logger = logging.getLogger("collector")


def poll_one_router(router_id: str, router: RouterClient, db: Database,
                     measure_latency: bool) -> None:
    if not router.authorize():
        logger.warning("공유기 '%s' SSH 연결 실패 - 이번 주기는 건너뜀", router_id)
        return
    try:
        devices = router.get_connected_devices()
        approved_macs = set(router.list_approved_macs())
        for d in devices:
            changed = db.upsert_device(d.mac, router_id, d.ip, d.hostname, d.is_online)
            if changed and firebase_sync.is_ready():
                firebase_sync.push_event(d.mac, "online" if d.is_online else "offline",
                                          d.hostname, int(time.time()))
            if d.is_online and measure_latency:
                db.set_latency(d.mac, ping_ms(d.ip))
            db.set_approved(d.mac, d.mac.upper() in approved_macs)

        db.mark_all_offline_except({d.mac for d in devices if d.is_online})

        if firebase_sync.is_ready():
            wifi_status = router.get_wifi_status()
            firebase_sync.push_wifi_status({router_id: wifi_status})
    finally:
        router.logout()


def poll_all(routers: dict[str, RouterClient], db: Database, measure_latency: bool) -> None:
    for router_id, router in routers.items():
        poll_one_router(router_id, router, db, measure_latency)

    if firebase_sync.is_ready():
        firebase_sync.push_devices(db.list_devices())
        firebase_sync.push_routers(db.list_routers())
        firebase_sync.sync_accounts()


def process_commands(routers: dict[str, RouterClient], pihole: PiholeClient,
                      db: Database) -> None:
    """휴대폰 앱이 Firestore 'commands'에 남긴 명령을 실행한다."""
    if not firebase_sync.is_ready():
        return
    for cmd in firebase_sync.fetch_pending_commands():
        cmd_id = cmd["id"]
        cmd_type = cmd.get("type")
        payload = cmd.get("payload", {})
        try:
            if cmd_type == "toggle_guest_wifi":
                router = routers.get(payload.get("router_id"))
                if router and router.authorize():
                    router.set_guest_wifi(payload.get("band", "2g"), payload.get("enable", True))
                    router.logout()
                firebase_sync.mark_command_done(cmd_id, True)
            elif cmd_type == "block_domain":
                ok = pihole.block_domain(payload.get("domain", ""))
                firebase_sync.mark_command_done(cmd_id, ok)
            elif cmd_type == "unblock_domain":
                ok = pihole.unblock_domain(payload.get("domain", ""))
                firebase_sync.mark_command_done(cmd_id, ok)
            elif cmd_type == "set_approved":
                mac = payload.get("mac", "")
                approved = bool(payload.get("approved"))
                any_openwrt = any(r.mode == "openwrt" for r in routers.values())
                for router in routers.values():
                    if router.authorize():
                        if approved:
                            router.approve_device(mac)
                        else:
                            router.unapprove_device(mac)
                        router.logout()
                db.set_approved(mac, approved)
                if any_openwrt:
                    firebase_sync.mark_command_done(cmd_id, True, "공유기에 실제 반영됨")
                else:
                    firebase_sync.mark_command_done(
                        cmd_id, True,
                        "기록만 저장됨 - 스캔 모드라 실제 차단은 적용되지 않음 "
                        "(OpenWrt 전환 후 자동으로 실제 차단됨)"
                    )
            elif cmd_type == "rename_router":
                db.rename_router(payload.get("router_id", ""), payload.get("label", ""))
                firebase_sync.mark_command_done(cmd_id, True)
            elif cmd_type == "set_alias":
                db.set_alias(payload.get("mac", ""), payload.get("alias", ""))
                firebase_sync.mark_command_done(cmd_id, True)
            elif cmd_type == "set_account_role":
                firebase_sync.set_account_role(
                    payload.get("uid", ""), bool(payload.get("make_admin"))
                )
                firebase_sync.sync_accounts()
                firebase_sync.mark_command_done(cmd_id, True)
            elif cmd_type == "reboot_router":
                router = routers.get(payload.get("router_id"))
                if router and router.authorize():
                    router.reboot()
                firebase_sync.mark_command_done(cmd_id, True)
            else:
                firebase_sync.mark_command_done(cmd_id, False, f"알 수 없는 명령: {cmd_type}")
        except Exception as e:  # noqa: BLE001
            logger.error("명령 처리 실패(%s): %s", cmd_type, e)
            firebase_sync.mark_command_done(cmd_id, False, str(e))


def run_forever(cfg: dict) -> None:
    routers: dict[str, RouterClient] = {}
    db = Database(cfg["database"]["path"])

    for r in cfg["routers"]:
        routers[r["id"]] = RouterClient(
            mode=r.get("mode", "scan"),
            host=r.get("host", ""),
            username=r.get("username", "root"),
            password=r.get("password"),
            key_path=r.get("key_path"),
            port=r.get("port", 22),
            subnet=r.get("subnet"),
        )
        db.upsert_router(r["id"], r.get("label", r["id"]))

    pihole = PiholeClient(
        cfg.get("pihole", {}).get("base_url", "http://127.0.0.1"),
        cfg.get("pihole", {}).get("password", ""),
    )

    firebase_cfg = cfg.get("firebase", {})
    if firebase_cfg.get("enabled"):
        firebase_sync.init(firebase_cfg.get("service_account_path", "serviceAccountKey.json"))

    interval = cfg["polling"]["interval_seconds"]
    measure_latency = cfg["polling"].get("measure_latency", True)
    logger.info("수집기 시작 - 공유기 %d대, %d초 간격", len(routers), interval)
    while True:
        try:
            poll_all(routers, db, measure_latency)
            process_commands(routers, pihole, db)
        except Exception as e:  # noqa: BLE001
            logger.error("폴링 중 오류: %s", e)
        time.sleep(interval)


if __name__ == "__main__":
    import yaml

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    with open("config.yaml", encoding="utf-8") as f:
        loaded_cfg = yaml.safe_load(f)
    run_forever(loaded_cfg)