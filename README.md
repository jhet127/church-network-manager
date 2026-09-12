# 교회 네트워크 통합 관리 시스템

TP-Link AX5400(Archer AX73) 기반 교회 내부망을 위한 관리 시스템입니다.

## 구성

```
church-network-manager/
├── raspberry-pi/     # 라즈베리파이에서 상시 구동 (공유기 폴링, 로컬 대시보드, Firestore 업로드)
│   └── raspberry-pi/README.md 참고
└── firebase/         # 휴대폰 등 외부에서 접속하는 웹 앱 + 실시간 데이터 저장소
    └── firebase/README.md 참고
```

## 전체 동작 원리

1. **라즈베리파이**가 30초마다 TP-Link 공유기를 확인해 접속 기기/Wi-Fi 상태를 로컬 SQLite에 저장
2. `firebase.enabled: true`로 설정하면, 같은 정보를 **Firestore**(구글 클라우드 DB)에도 올림
3. **휴대폰 앱**(Firebase Hosting에 배포된 웹앱)은 어디서든 Firestore를 실시간으로 읽어 화면에 표시
4. 휴대폰에서 "게스트 Wi-Fi 끄기" 같은 조작을 하면 Firestore의 `commands`에 명령이 쌓이고,
   라즈베리파이가 이를 읽어 실제 공유기에 적용

즉 라즈베리파이가 없으면 앱은 화면만 뜨고 아무 데이터도 안 보이는 게 정상입니다.
먼저 라즈베리파이 없이 **Firebase 프로젝트와 GitHub 저장소부터 만들어두고**, 이후
라즈베리파이가 준비되면 연결하는 순서로 진행하면 됩니다.

## 지금 할 일 순서

1. GitHub에 빈 저장소 생성 → 이 폴더를 그대로 push
2. Firebase 콘솔(console.firebase.google.com)에서 프로젝트 생성
   → `firebase/` 폴더의 안내(firebase/README.md)를 따라 Hosting + Firestore + Auth 설정
3. 라즈베리파이 도착하면 `raspberry-pi/README.md`를 따라 설치, `config.yaml`의 `firebase.enabled: true`로 변경
