# 라즈베리파이 - 로컬 수집기 + 로컬 대시보드

두 가지 모드를 지원합니다. `config.yaml`의 `routers` 항목에서 `mode` 값만 바꾸면 됩니다.

| 모드 | 지금 가능? | 할 수 있는 것 | 공유기에 영향 |
|---|---|---|---|
| **`scan`** (기본값) | ✅ 지금 당장 | 접속 기기 목록 조회만 (읽기 전용) | 전혀 없음 (공유기 설정 안 건드림) |
| **`openwrt`** | 공유기를 OpenWrt로 바꾼 뒤 | 위 기능 + 승인/차단 실제 강제, Wi-Fi on/off, 재부팅 | SSH로 직접 제어 |

**지금 메인 공유기가 실사용 중이라면 `scan` 모드로 시작하세요.** 안전하게 모니터링부터
시작하고, 나중에 시간 여유가 있을 때(예비 시간대에) OpenWrt 설치를 진행한 뒤
`mode: "openwrt"`로 바꾸면 승인/차단까지 자동으로 켜집니다. 코드 수정은 필요 없습니다.

## 0. OpenWrt 공유기 초기 설정 (openwrt 모드 전환 시에만 필요, 최초 1회)

**이 절은 `mode: "openwrt"`로 전환할 준비가 됐을 때만 진행하세요.**
`scan` 모드로 쓰는 동안에는 건너뛰어도 됩니다.

공유기에 OpenWrt를 설치하고 root 비밀번호까지 설정하셨다면, 컴퓨터에서:

```bash
ssh root@192.168.1.1
```

공유기 안에 접속되면, 아래 명령들을 그대로 붙여넣으세요.

```sh
# 1. 승인된 기기를 담을 목록(세트)을 만든다
nft add set inet fw4 approved_macs '{ type ether_addr; }'

# 2. LAN에서 나가는 트래픽 중, 이 목록에 없는 MAC은 차단하는 규칙을 추가한다
nft insert rule inet fw4 forward ether saddr != @approved_macs counter drop

# 3. 지금 이미 접속 중인 우리집 기기들을 먼저 승인해둔다 (안 그러면 전부 끊김!)
#    아래 명령으로 지금 접속된 기기의 MAC 주소를 확인한 뒤,
cat /tmp/dhcp.leases
#    나온 MAC 주소들을 하나씩 승인 목록에 추가 (예시)
nft add element inet fw4 approved_macs '{ aa:bb:cc:dd:ee:ff }'
```

**⚠️ 이 3단계를 하는 순간부터, 목록에 없는 기기는 즉시 인터넷이 끊깁니다.**
꼭 지금 쓰고 있는 컴퓨터/휴대폰의 MAC 주소부터 먼저 승인 목록에 넣어두고 진행하세요
(안 그러면 본인 접속도 끊겨서 재부팅으로 되돌려야 할 수 있습니다).

이후로는 이 화면을 다시 열 필요 없이, **앱/대시보드의 승인 버튼이 이 목록을 자동으로 관리**합니다.

## 1. 라즈베리파이 설치

```bash
sudo apt update && sudo apt install -y python3-venv git
cd /home/pi/church-network-manager/raspberry-pi
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp config.yaml.example config.yaml
nano config.yaml
```

`config.yaml`에서 `routers` 항목에 공유기 SSH 정보(IP, `root`, 비밀번호)를 입력하세요.
비밀번호 대신 SSH 키를 쓰고 싶으면 `key_path`를 채우고 `password`는 지워도 됩니다.

`config.yaml`은 `.gitignore`에 포함되어 있어 GitHub에 올라가지 않습니다.

## 2. 수동 실행 테스트

```bash
python -m app.collector        # 터미널 1: 공유기 SSH 폴링
uvicorn app.main:app --host 0.0.0.0 --port 8000   # 터미널 2: 로컬 대시보드
```

`http://<라즈베리파이IP>:8000` 접속해 확인. 접속 기기 목록, Wi-Fi 상태가 보이고
승인 버튼을 누르면 실제로 그 기기의 인터넷이 끊기는지(또는 다시 붙는지) 확인해보세요.

## 3. 상시 구동 등록 (systemd)

```bash
sudo cp deploy/church-network-web.service /etc/systemd/system/
sudo cp deploy/church-network-collector.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now church-network-web
sudo systemctl enable --now church-network-collector
```

## 4. Pi-hole (사이트 차단, 선택)

```bash
curl -sSL https://install.pi-hole.net | bash
```

설치 후 나오는 관리자 비밀번호를 `config.yaml`의 `pihole.password`에 입력.
공유기의 DHCP 설정(OpenWrt LuCI 웹 화면 또는 `uci set dhcp.lan.dhcp_option='6,<라즈베리파이IP>'`)에서
DNS 서버 주소를 라즈베리파이 IP로 지정해야 전체 네트워크에 적용됩니다.

## 5. Firebase 연동 (휴대폰 앱과 연결)

1. `../firebase/README.md`대로 Firebase 프로젝트를 먼저 만들어두세요.
2. Firebase 콘솔 > 프로젝트 설정 > 서비스 계정 > "새 비공개 키 생성" → 다운로드한 JSON을
   `raspberry-pi/serviceAccountKey.json`으로 저장.
3. `config.yaml`에서:
   ```yaml
   firebase:
     enabled: true
     service_account_path: "serviceAccountKey.json"
   ```
4. 재시작:
   ```bash
   sudo systemctl restart church-network-collector
   ```

### 5-1. 계정 관리 기능도 자동으로 켜짐

5번을 완료하면, 앱의 "계정 관리" 화면(설정 → 내 정보)도 별도 설정 없이 바로 동작합니다.

## 6. 미승인 기기 차단 — 이제 완전 자동입니다

예전에는 여기서 "메인 공유기 관리 페이지에 수동으로 등록하세요"라고 안내했지만,
**OpenWrt로 바뀐 지금은 필요 없습니다.** 앱이나 로컬 대시보드에서 승인 버튼을 누르면
`nft add/delete element` 명령이 SSH로 즉시 공유기에 전달되어, 그 순간부터 실제로
인터넷이 통하거나 끊깁니다. 고정 IP를 직접 입력해도 MAC 주소가 승인 목록에 없으면
방화벽 규칙(0단계에서 만든 것)이 트래픽 자체를 막습니다.

## JSON API (참고용 - 로컬 대시보드 서버 자체에도 있음)

| 엔드포인트 | 설명 |
|---|---|
| `GET /api/devices` | 공유기별로 그룹화된 접속 기기 목록 |
| `GET /api/events?limit=50` | 최근 접속/해제 이력 |

이 API는 라즈베리파이가 켜져 있고 같은 네트워크(또는 VPN)에 있을 때만 동작합니다.
교회 밖에서 쓰려면 Firebase 연동(5번)을 사용하세요.
