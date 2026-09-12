"""웹 대시보드. 브라우저로 접속해 공유기별 기기 목록/Wi-Fi 상태를 확인·조작한다."""
from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .db import Database
from .pihole_client import PiholeClient
from .router_client import RouterClient

BASE_DIR = Path(__file__).resolve().parent.parent

with open(BASE_DIR / "config.yaml", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

app = FastAPI(title="교회 네트워크 관리 시스템")
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")

db = Database(CONFIG["database"]["path"])

routers: dict[str, RouterClient] = {}
for r in CONFIG["routers"]:
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

pihole_client = PiholeClient(
    CONFIG.get("pihole", {}).get("base_url", "http://127.0.0.1"),
    CONFIG.get("pihole", {}).get("password", ""),
)
ALIASES = CONFIG.get("device_aliases") or {}


def _apply_aliases(devices: list[dict]) -> list[dict]:
    for d in devices:
        if d.get("alias"):
            continue
        if d["mac"] in ALIASES:
            d["alias"] = ALIASES[d["mac"]]
    return devices


@app.get("/")
def dashboard(request: Request):
    _apply_aliases(db.list_devices())  # config의 device_aliases를 DB에 반영된 것처럼 병합
    groups = db.list_devices_grouped_by_router()
    for g in groups:
        _apply_aliases(g["devices"])
    online_count = sum(1 for g in groups for d in g["devices"] if d["is_online"])
    total_count = sum(len(g["devices"]) for g in groups)
    events = db.recent_events(20)

    wifi_statuses = {}
    wifi_errors = {}
    for router_id, router in routers.items():
        try:
            if router.authorize():
                wifi_statuses[router_id] = router.get_wifi_status()
                router.logout()
            else:
                wifi_errors[router_id] = "공유기 인증 실패 - config.yaml의 비밀번호를 확인하세요."
        except Exception as e:  # noqa: BLE001
            wifi_errors[router_id] = f"공유기 연결 실패: {e}"

    router_labels = {r["id"]: r["label"] for r in db.list_routers()}

    blocked_domains = pihole_client.list_blocked_domains()
    pihole_status = pihole_client.get_status()
    whitelist = db.list_whitelist()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "groups": groups,
            "router_labels": router_labels,
            "online_count": online_count,
            "total_count": total_count,
            "events": events,
            "wifi_statuses": wifi_statuses,
            "wifi_errors": wifi_errors,
            "blocked_domains": blocked_domains,
            "pihole_status": pihole_status,
            "whitelist": whitelist,
            "main_router_note": CONFIG.get("access_control", {}).get("main_router_note", ""),
            "any_openwrt": any(r.mode == "openwrt" for r in routers.values()),
        },
    )


@app.post("/router/rename")
def rename_router(router_id: str = Form(...), label: str = Form(...)):
    db.rename_router(router_id, label.strip())
    return RedirectResponse("/", status_code=303)


@app.post("/device/approve")
def approve_device(mac: str = Form(...), approved: str = Form(...)):
    # approved 값은 폼에서 "1"/"0" 문자열로 넘어온다.
    is_approved = approved == "1"
    for router in routers.values():
        try:
            if router.authorize():
                if is_approved:
                    router.approve_device(mac)
                else:
                    router.unapprove_device(mac)
                router.logout()
        except Exception:
            pass
    db.set_approved(mac, is_approved)
    return RedirectResponse("/", status_code=303)


@app.post("/alias")
def update_alias(mac: str = Form(...), alias: str = Form("")):
    db.set_alias(mac, alias)
    return RedirectResponse("/", status_code=303)


@app.post("/blocklist/add")
def add_blocked_domain(domain: str = Form(...)):
    pihole_client.block_domain(domain.strip())
    return RedirectResponse("/", status_code=303)


@app.post("/blocklist/remove")
def remove_blocked_domain(domain: str = Form(...)):
    pihole_client.unblock_domain(domain.strip())
    return RedirectResponse("/", status_code=303)


@app.post("/whitelist/add")
def add_whitelist(mac: str = Form(...), label: str = Form("")):
    db.add_to_whitelist(mac.strip(), label.strip())
    return RedirectResponse("/", status_code=303)


@app.post("/whitelist/remove")
def remove_whitelist(mac: str = Form(...)):
    db.remove_from_whitelist(mac.strip())
    return RedirectResponse("/", status_code=303)


@app.post("/wifi/guest/{router_id}/{band}/{action}")
def toggle_guest_wifi(router_id: str, band: str, action: str):
    enable = action == "on"
    router = routers.get(router_id)
    try:
        if router and router.authorize():
            router.set_guest_wifi(band, enable)
            router.logout()
    except Exception:
        pass
    return RedirectResponse("/", status_code=303)


@app.post("/router/{router_id}/reboot")
def reboot_router(router_id: str):
    router = routers.get(router_id)
    try:
        if router and router.authorize():
            router.reboot()
    except Exception:
        pass
    return RedirectResponse("/", status_code=303)


# ----------------------------------------------------------------------
# JSON API - 휴대폰 등 외부 클라이언트에서 쓰기 위한 엔드포인트
# ----------------------------------------------------------------------

@app.get("/api/devices")
def api_devices():
    return {"groups": db.list_devices_grouped_by_router()}


@app.get("/api/events")
def api_events(limit: int = 50):
    return {"events": db.recent_events(limit)}
