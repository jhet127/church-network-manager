// 교회 네트워크 관리 - 웹 앱
//
// 사용 전 아래 firebaseConfig를 본인의 Firebase 프로젝트 값으로 채우세요.
// Firebase 콘솔 > 프로젝트 설정 > 일반 > 내 앱 > SDK 설정 및 구성 에서 복사할 수 있습니다.
//
// 데이터는 실시간 스트리밍이 아니라, 새로고침 버튼 또는 자동 새로고침 주기(10~30초)에
// 맞춰 그때그때 한 번씩 불러오는 방식입니다. 공유기 20대·기기 50대 규모에서는
// 어느 쪽이든 트래픽 차이가 크지 않지만, 데이터 사용량을 사용자가 직접 통제할 수 있도록
// 이 방식을 사용합니다.

import { initializeApp } from "https://www.gstatic.com/firebasejs/10.13.0/firebase-app.js";
import {
  getAuth, signInWithEmailAndPassword, onAuthStateChanged, signOut,
  EmailAuthProvider, reauthenticateWithCredential, updatePassword,
} from "https://www.gstatic.com/firebasejs/10.13.0/firebase-auth.js";
import {
  getFirestore, collection, doc, getDoc, getDocs, setDoc, deleteDoc, addDoc,
  query, orderBy, limit, serverTimestamp,
} from "https://www.gstatic.com/firebasejs/10.13.0/firebase-firestore.js";

const firebaseConfig = {
  apiKey: "여기에_API_KEY",
  authDomain: "여기에_프로젝트ID.firebaseapp.com",
  projectId: "여기에_프로젝트ID",
  storageBucket: "여기에_프로젝트ID.appspot.com",
  messagingSenderId: "여기에_SENDER_ID",
  appId: "여기에_APP_ID",
};

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const db = getFirestore(app);

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------------
// 로그인
// ---------------------------------------------------------------------
$("login-btn").addEventListener("click", async () => {
  $("login-error").textContent = "";
  try {
    await signInWithEmailAndPassword(auth, $("email").value, $("password").value);
  } catch (e) {
    console.error(e);
    $("login-error").textContent = `로그인 실패 (${e.code}): 이메일/비밀번호를 확인하세요.`;
  }
});

$("logout-btn").addEventListener("click", () => {
  stopAutoRefresh();
  signOut(auth);
});

let isAdmin = false;

onAuthStateChanged(auth, async (user) => {
  $("login-screen").style.display = user ? "none" : "flex";
  $("dashboard-screen").style.display = user ? "block" : "none";
  if (user) {
    $("account-email").textContent = user.email || "-";
    try {
      const roleDoc = await getDoc(doc(db, "users", user.uid));
      isAdmin = roleDoc.exists() && roleDoc.data().role === "admin";
    } catch (e) {
      isAdmin = false; // 등급 조회 실패 시 안전하게 읽기 전용으로 취급
    }
    $("role-badge").textContent = isAdmin ? "관리자" : "보기 전용";
    $("role-badge").className = isAdmin ? "role-badge admin" : "role-badge viewer";
    document.body.classList.toggle("role-viewer", !isAdmin);
    fetchAll();
    startAutoRefresh();
  }
});

// ---------------------------------------------------------------------
// 설정 드롭다운 / 설정 모달
// ---------------------------------------------------------------------
$("settings-btn").addEventListener("click", (e) => {
  e.stopPropagation();
  $("settings-menu").hidden = !$("settings-menu").hidden;
});
document.addEventListener("click", () => { $("settings-menu").hidden = true; });

$("my-info-btn").addEventListener("click", () => {
  $("settings-menu").hidden = true;
  $("settings-modal").hidden = false;
  if (isAdmin) loadAccountList();
});
$("settings-close-btn").addEventListener("click", () => { $("settings-modal").hidden = true; });
$("settings-done-btn").addEventListener("click", () => { $("settings-modal").hidden = true; });

// ---------------------------------------------------------------------
// 계정 관리 (관리자 전용) — 라즈베리파이가 올려주는 'accounts' 컬렉션을 읽고,
// 권한 변경은 'commands'에 요청을 남기면 라즈베리파이가 처리한다.
// (라즈베리파이 연동 전에는 목록이 비어있는 게 정상입니다.)
// ---------------------------------------------------------------------
async function loadAccountList() {
  const el = $("account-list");
  el.textContent = "불러오는 중...";
  try {
    const snap = await getDocs(collection(db, "accounts"));
    if (snap.empty) {
      el.textContent = "아직 계정 목록이 없습니다 (라즈베리파이 연동 전이거나, 첫 동기화 대기 중).";
      return;
    }
    const accounts = [];
    snap.forEach((d) => accounts.push({ uid: d.id, ...d.data() }));

    el.innerHTML = accounts.map((acc) => `
      <div class="account-row">
        <span class="email">${acc.email}</span>
        <label>
          <input type="checkbox" class="role-checkbox" data-uid="${acc.uid}"
                 ${acc.role === "admin" ? "checked" : ""}
                 ${acc.uid === auth.currentUser.uid ? "disabled" : ""}>
          관리자 권한
        </label>
      </div>`).join("");

    document.querySelectorAll(".role-checkbox").forEach((cb) => {
      cb.addEventListener("change", async () => {
        cb.disabled = true;
        await sendCommand("set_account_role", { uid: cb.dataset.uid, make_admin: cb.checked });
        const row = cb.closest(".account-row");
        const note = document.createElement("p");
        note.className = "modal-hint";
        note.textContent = "요청됨 - 라즈베리파이가 처리할 때까지 최대 몇십 초 걸릴 수 있어요.";
        row.after(note);
        cb.disabled = cb.dataset.uid !== auth.currentUser.uid;
      });
    });
  } catch (e) {
    el.textContent = "계정 목록을 불러오지 못했습니다: " + e.message;
  }
}

$("change-password-btn").addEventListener("click", async () => {
  const currentPassword = $("current-password").value;
  const newPassword = $("new-password").value;
  const msg = $("password-msg");
  msg.style.color = "#999";
  msg.textContent = "";

  if (!currentPassword || !newPassword) {
    msg.style.color = "#dc2626";
    msg.textContent = "현재 비밀번호와 새 비밀번호를 모두 입력하세요.";
    return;
  }
  if (newPassword.length < 6) {
    msg.style.color = "#dc2626";
    msg.textContent = "새 비밀번호는 6자 이상이어야 합니다.";
    return;
  }

  try {
    const user = auth.currentUser;
    // 보안을 위해 비밀번호를 바꾸기 전, 현재 비밀번호로 다시 한 번 본인 확인을 한다.
    const credential = EmailAuthProvider.credential(user.email, currentPassword);
    await reauthenticateWithCredential(user, credential);
    await updatePassword(user, newPassword);
    msg.style.color = "#16a34a";
    msg.textContent = "비밀번호가 변경되었습니다.";
    $("current-password").value = "";
    $("new-password").value = "";
  } catch (e) {
    msg.style.color = "#dc2626";
    msg.textContent = "변경 실패: 현재 비밀번호가 올바른지 확인하세요.";
  }
});

// ---------------------------------------------------------------------
// 새로고침 버튼 / 자동 새로고침 주기 설정
// ---------------------------------------------------------------------
let autoRefreshTimer = null;

function startAutoRefresh() {
  stopAutoRefresh();
  const seconds = parseInt($("auto-refresh-select").value, 10);
  if (seconds > 0) {
    autoRefreshTimer = setInterval(fetchAll, seconds * 1000);
  }
}

function stopAutoRefresh() {
  if (autoRefreshTimer) {
    clearInterval(autoRefreshTimer);
    autoRefreshTimer = null;
  }
}

$("refresh-btn").addEventListener("click", fetchAll);
$("auto-refresh-select").addEventListener("change", startAutoRefresh);

// ---------------------------------------------------------------------
// 데이터 한 번에 불러오기 (Firestore)
// ---------------------------------------------------------------------
let routerLabels = {};   // { router_id: label }
let allDevices = [];     // 최근 devices 조회 결과

async function fetchAll() {
  $("refresh-btn").disabled = true;
  try {
    await Promise.all([fetchRouters(), fetchDevices(), fetchBlocklist(), fetchEvents()]);
    $("last-updated").textContent = `마지막 업데이트: ${new Date().toLocaleTimeString("ko-KR")}`;
  } catch (e) {
    $("last-updated").textContent = "업데이트 실패 - 잠시 후 다시 시도하세요.";
  } finally {
    $("refresh-btn").disabled = false;
  }
}

async function fetchRouters() {
  const snap = await getDocs(collection(db, "routers"));
  routerLabels = {};
  snap.forEach((d) => { routerLabels[d.id] = d.data().label || d.id; });
}

async function fetchDevices() {
  const snap = await getDocs(collection(db, "devices"));
  allDevices = [];
  snap.forEach((d) => allDevices.push({ mac: d.id, ...d.data() }));
  renderDeviceGroups();
}

async function fetchBlocklist() {
  const snap = await getDocs(collection(db, "blocklist"));
  const items = [];
  snap.forEach((d) => {
    const removeBtn = isAdmin
      ? `<button data-domain="${d.id}" class="remove-domain">해제</button>` : "";
    items.push(`<li>${d.id} ${removeBtn}</li>`);
  });
  $("blocklist").innerHTML = items.join("") || "<li>차단 중인 사이트 없음</li>";
  if (!isAdmin) return;
  document.querySelectorAll(".remove-domain").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await deleteDoc(doc(db, "blocklist", btn.dataset.domain));
      fetchBlocklist();
    });
  });
}

async function fetchEvents() {
  const eventsQuery = query(collection(db, "events"), orderBy("ts", "desc"), limit(20));
  const snap = await getDocs(eventsQuery);
  const items = [];
  snap.forEach((d) => {
    const v = d.data();
    items.push(`<li>${v.hostname || v.mac} ${v.event === "online" ? "접속함" : "접속 해제됨"}</li>`);
  });
  $("event-list").innerHTML = items.join("");
}

function renderDeviceGroups() {
  const groups = {};
  for (const d of allDevices) {
    const rid = d.router_id || "unknown";
    if (!groups[rid]) groups[rid] = [];
    groups[rid].push(d);
  }

  let onlineCount = 0;
  const html = Object.entries(groups).map(([rid, devices]) => {
    const label = routerLabels[rid] || rid;
    const rows = devices.map((d) => {
      if (d.is_online) onlineCount++;
      const name = d.alias || d.hostname || "(이름 없음)";
      const latency = (d.latency_ms ?? null) !== null ? `${d.latency_ms} ms` : "-";
      const approved = !!d.approved;
      const approveCell = isAdmin
        ? `<button class="approve-btn ${approved ? "approved" : "unapproved"}"
                    data-mac="${d.mac}" data-next="${approved ? 0 : 1}">
              ${approved ? "✅ 승인됨" : "🚫 미승인"}
            </button>`
        : `<span class="approve-badge ${approved ? "approved" : "unapproved"}">
              ${approved ? "✅ 승인됨" : "🚫 미승인"}
            </span>`;
      return `
        <tr class="${d.is_online ? "online" : "offline"}">
          <td>${d.is_online ? "🟢" : "⚪"}</td>
          <td>${name}</td>
          <td>${d.ip || ""}</td>
          <td class="mac">${d.mac}</td>
          <td>${latency}</td>
          <td>${approveCell}</td>
        </tr>`;
    }).join("");

    const renameControls = isAdmin
      ? `<div class="row" style="margin:6px 0;">
          <input type="text" class="rename-input" data-rid="${rid}" placeholder="공유기 이름" value="${label}">
          <button class="rename-btn" data-rid="${rid}">저장</button>
        </div>`
      : "";

    return `
      <div class="router-group">
        <div class="router-header">
          <strong>📡 <span class="router-label" data-rid="${rid}">${label}</span></strong>
          ${renameControls}
        </div>
        <table>
          <thead>
            <tr><th>상태</th><th>단말명</th><th>IP</th><th>MAC</th><th>지연시간</th><th>승인</th></tr>
          </thead>
          <tbody>${rows || `<tr><td colspan="6">등록된 기기가 없습니다.</td></tr>`}</tbody>
        </table>
      </div>`;
  }).join("") || "<p class='empty'>아직 연결된 공유기가 없습니다 (라즈베리파이 연동 전).</p>";

  $("device-groups").innerHTML = html;
  $("online-count").textContent = onlineCount;

  if (!isAdmin) return; // 뷰어는 조작 버튼이 없으므로 아래 이벤트 연결 불필요

  document.querySelectorAll(".approve-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const mac = btn.dataset.mac;
      const nextApproved = btn.dataset.next === "1";
      await setDoc(doc(db, "devices", mac), { approved: nextApproved }, { merge: true });
      await sendCommand("set_approved", { mac, approved: nextApproved });
      fetchDevices();
    });
  });

  document.querySelectorAll(".rename-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const rid = btn.dataset.rid;
      const input = document.querySelector(`.rename-input[data-rid="${rid}"]`);
      const label = input.value.trim();
      if (!label) return;
      await setDoc(doc(db, "routers", rid), { label }, { merge: true });
      await sendCommand("rename_router", { router_id: rid, label });
      fetchRouters().then(renderDeviceGroups);
    });
  });
}

// ---------------------------------------------------------------------
// 명령 보내기 (라즈베리파이가 폴링해서 실행)
// ---------------------------------------------------------------------
async function sendCommand(type, payload = {}) {
  await addDoc(collection(db, "commands"), {
    type, payload, status: "pending", createdAt: serverTimestamp(),
  });
}

$("add-domain-btn").addEventListener("click", async () => {
  const domain = $("domain-input").value.trim();
  if (!domain) return;
  await setDoc(doc(db, "blocklist", domain), { addedAt: serverTimestamp() });
  await sendCommand("block_domain", { domain });
  $("domain-input").value = "";
  fetchBlocklist();
});
