# Firebase - 휴대폰 앱 + 실시간 데이터 저장소

라즈베리파이 없이도 이 부분은 지금 바로 만들 수 있습니다 (화면은 뜨지만 데이터는
라즈베리파이 연동 전까지 비어있는 게 정상입니다).

## 1. Firebase 프로젝트 생성

1. https://console.firebase.google.com 접속 → "프로젝트 추가"
2. 프로젝트 이름 입력 (예: church-network-manager) → 생성

## 2. Firestore(데이터베이스) 활성화

콘솔 왼쪽 메뉴 > Firestore Database > "데이터베이스 만들기"
→ 위치는 `asia-northeast3(서울)` 권장 → 프로덕션 모드로 시작 (보안 규칙은 이미 만들어둠)

## 3. Authentication(로그인) 활성화

콘솔 > Authentication > "시작하기" > 로그인 방법에서 "이메일/비밀번호" 사용 설정
→ Users 탭에서 관리자 계정 1개를 직접 추가 (예: 본인 이메일 + 비밀번호)
→ 이 계정으로만 앱에 로그인해서 관리하게 됩니다.

## 4. 로컬 개발 도구 설치 및 로그인

```bash
npm install -g firebase-tools
firebase login
cd firebase
cp .firebaserc.example .firebaserc
```

`.firebaserc`를 열어 `"default"` 값을 방금 만든 실제 Firebase 프로젝트 ID로 바꾸세요.
(프로젝트 ID는 Firebase 콘솔 > 프로젝트 설정 상단에서 확인 가능)

## 5. 웹 앱 설정 값 채우기

Firebase 콘솔 > 프로젝트 설정 > 일반 > "내 앱" > 웹 앱 추가(`</>` 아이콘)
→ 나오는 `firebaseConfig` 값을 `firebase/public/app.js` 상단의 `firebaseConfig`에
그대로 복사해 넣으세요.

## 6. 배포

```bash
firebase deploy --only hosting,firestore:rules
```

배포가 끝나면 `https://<프로젝트ID>.web.app` 주소가 나옵니다. 이 주소가 휴대폰에서
접속할 앱 주소입니다. 브라우저로 열어 3번에서 만든 계정으로 로그인해보세요.
(라즈베리파이 연동 전이라 목록은 비어있는 게 정상입니다.)

## 7. 라즈베리파이와 연결

`../raspberry-pi/README.md`의 "5. Firebase 연동" 절을 진행하면 실시간으로
데이터가 채워지기 시작합니다.

## 8. 휴대폰에 앱처럼 설치

휴대폰 브라우저에서 `https://<프로젝트ID>.web.app` 접속 후
- iPhone(Safari): 공유 버튼 → "홈 화면에 추가"
- Android(Chrome): 메뉴(⋮) → "홈 화면에 추가"

## 9. 뷰어(읽기 전용) 계정 추가하기

관리자 계정 외에 "상태만 보고 아무것도 못 바꾸는" 계정을 추가할 수 있습니다.

### 9-1. 먼저, 지금 쓰고 있는 관리자 계정을 진짜 admin으로 등록

규칙을 새로 배포하면 기본적으로 **모든 계정이 뷰어(읽기 전용)**가 됩니다.
지금 쓰시는 관리자 계정도 예외가 아니라서, 아래 절차로 admin 등록을 해줘야
계속 설정을 바꿀 수 있습니다.

1. Firebase 콘솔 > Authentication > Users 탭 → 본인 계정의 **UID** 복사 (긴 영문/숫자 문자열)
2. Firebase 콘솔 > Firestore Database > 데이터 탭 → **"컬렉션 시작"**
3. 컬렉션 ID: `users` 입력
4. 문서 ID: 방금 복사한 UID를 그대로 붙여넣기
5. 필드 추가: 필드 이름 `role`, 값 `admin` (문자열) → 저장

### 9-2. 새 뷰어 계정 만들기

1. Firebase 콘솔 > Authentication > Users → "사용자 추가" → 이메일/비밀번호 입력해서 계정 생성
2. **여기서 끝입니다.** `users` 컬렉션에 아무 문서도 안 만들면, 그 계정은 자동으로 읽기 전용(뷰어)이 됩니다.

### 9-3. 이후로는 앱 안에서 권한 관리 가능 (라즈베리파이 연동 후)

계정을 새로 만드는 것 자체(9-2)는 여전히 Firebase 콘솔에서 해야 하지만,
**이미 만들어진 계정들의 권한(관리자 ↔ 뷰어)은 라즈베리파이가 연동되면 앱 안에서
바로 바꿀 수 있습니다.** 관리자로 로그인 → ⚙️ 설정 → 내 정보 → "계정 관리"에서
계정별로 체크박스를 켜고 끄면, 그 요청이 라즈베리파이로 전달되어 실제로 반영됩니다.
(라즈베리파이 연동 전에는 이 목록이 비어있는 게 정상입니다. 결제 등록이나
Cloud Functions 같은 별도 설정 없이, 라즈베리파이가 이미 가진 관리자 권한을
그대로 활용하는 방식이라 추가 비용이 들지 않습니다.)

## 10. 로고 바꾸기

`firebase/public/index.html`에서 SVG로 그려진 기본 로고(파란 원 모양)를 실제 교회 로고 이미지로
바꾸고 싶다면, 로고 이미지 파일(png/svg)을 `firebase/public/logo.png`로 저장한 뒤
`index.html`의 `<svg>...</svg>` 부분을 `<img src="logo.png" width="40" height="40">`로 교체하면 됩니다.
