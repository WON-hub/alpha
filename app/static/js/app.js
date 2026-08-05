import { api } from "./api.js";

const FIXED_BUDGET = 12000;
const state = {
  affiliations: [],
  location: { lat: 37.6194, lng: 127.0598, source: "campus_default" },
  results: [],
  aiRecommendation: null,
  markers: [],
  map: null,
  userMarker: null,
  supabase: null,
  user: null,
};

const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
const unique = (items = []) => [...new Set(items.filter(Boolean))];
const listHtml = (items, className = "benefit-list") => `<ul class="${className}">${unique(items).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;

function toast(message) {
  const node = $("#toast");
  if (!node) return;
  node.textContent = message;
  node.classList.add("show");
  setTimeout(() => node.classList.remove("show"), 2800);
}

function flattenAffiliations(nodes, depth = 0) {
  return nodes.flatMap((node) => [{ ...node, depth }, ...flattenAffiliations(node.children || [], depth + 1)]);
}

function affiliationOptions(includePlaceholder = true) {
  const flattened = flattenAffiliations(state.affiliations)
    .filter((item) => item.type !== "university")
  const all = flattened.filter((item) => item.name === "전체");
  const options = [...all, ...flattened.filter((item) => item.name !== "전체")]
    .map((item) => `<option value="${item.id}">${item.name === "전체" ? "" : "　".repeat(item.depth)}${escapeHtml(item.name)}</option>`)
    .join("");
  return `${includePlaceholder ? '<option value="">소속을 선택하세요</option>' : ""}${options}`;
}

function updateSummary() {
  const count = [...document.querySelectorAll("#companions input")].reduce((sum, node) => sum + Number(node.value || 0), 1);
  if ($("#total-people")) $("#total-people").textContent = `${count}명`;
}

function addCompanion() {
  const row = document.createElement("div");
  row.className = "companion-row";
  row.innerHTML = `<select aria-label="동행자 소속">${affiliationOptions()}</select><input type="number" min="1" max="50" value="1" aria-label="동행자 인원" /><button type="button" class="remove-companion" aria-label="동행자 삭제">×</button>`;
  row.querySelector(".remove-companion").addEventListener("click", () => {
    row.remove();
    updateSummary();
  });
  row.querySelector("input").addEventListener("input", updateSummary);
  $("#companions").appendChild(row);
}

function initMap() {
  state.map = L.map("map", { zoomControl: false }).setView([state.location.lat, state.location.lng], 15);
  L.control.zoom({ position: "bottomright" }).addTo(state.map);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "© OpenStreetMap" }).addTo(state.map);
  state.userMarker = L.circleMarker([state.location.lat, state.location.lng], { radius: 8, color: "#641E32", fillColor: "#D4AF37", fillOpacity: 1, weight: 4 }).addTo(state.map).bindTooltip("내 위치", { direction: "top" });
}

function refreshMap(results = []) {
  state.markers.forEach((marker) => marker.remove());
  state.markers = results.map((result, index) => {
    const icon = L.divIcon({ className: "rank-marker", html: `<span>${index + 1}</span>`, iconSize: [29, 29], iconAnchor: [14, 14] });
    const marker = L.marker([result.latitude, result.longitude], { icon }).addTo(state.map);
    marker.on("click", () => openDetail(result.id));
    return marker;
  });
  if (results.length) state.map.fitBounds(L.latLngBounds(results.map((item) => [item.latitude, item.longitude])).pad(0.15));
}

function resultCard(item, index, isAi = false) {
  const colleges = item.eligible_colleges?.length ? item.eligible_colleges : item.eligible_affiliations;
  return `<article class="result-card ${isAi ? "top-one" : ""}" data-id="${item.id}">
    <div class="result-top"><div class="rank-name"><span class="rank">${isAi ? "✦" : index + 1}</span><div><div class="restaurant-name">${escapeHtml(item.name)}<span class="category-chip">${escapeHtml(item.category)}</span></div><div class="rating-line">★ ${Number(item.rating_average || 0).toFixed(1)} <span>${item.review_count ? `리뷰 ${item.review_count}개` : "리뷰 준비 중"}</span></div></div></div>${isAi ? '<span class="top-badge">AI 추천 매장</span>' : ""}</div>
    <div class="store-summary"><div class="content-label">AI 가게 요약</div><p>${escapeHtml(item.ai_store_summary)}</p></div>
    ${isAi ? `<div class="store-summary" style="border-left-color:#6D8B3D"><div class="content-label" style="color:#6D8B3D">AI 추천 이유</div><p>${escapeHtml(item.ai_recommendation_reason || "현재 조건에 잘 맞는 매장으로 선정했어요.")}</p></div>` : ""}
    <div class="benefit-block"><div class="benefit-heading"><strong>제휴 혜택</strong><span class="grade-badge">${escapeHtml(item.benefit_grade_emoji)} ${escapeHtml(item.benefit_grade)}</span></div>${listHtml(item.benefit_items)}</div>
    <div class="eligibility-block"><div class="content-label">적용 대상 소속</div><div class="eligibility-chips">${unique(colleges).map((college) => `<span>${escapeHtml(college)}</span>`).join("") || "<span>적용 대상 확인 필요</span>"}</div></div>
    <div class="meta-line"><span>↗ ${Number(item.distance_m).toLocaleString()}m · 도보 약 ${item.walking_minutes}분</span></div>
    <div class="reason-list">${item.reasons.map((reason) => `<span class="reason">${escapeHtml(reason)}</span>`).join("")}</div>
    <div class="card-actions"><button class="card-action detail-action" type="button">상세 보기</button><button class="card-action direction-action" type="button">길 찾기</button></div>
  </article>`;
}

function renderResults(results = state.results) {
  const list = $("#results-list");
  const empty = $("#result-state");
  if (!results.length && !state.aiRecommendation) {
    list.hidden = true;
    empty.hidden = false;
    empty.innerHTML = '<div class="empty-icon">✦</div><h3>조건에 맞는 제휴 식당이 없어요</h3><p>소속이나 결제 방식을 바꿔 다시 검색해 보세요.</p>';
    return;
  }
  empty.hidden = true;
  list.hidden = false;
  list.innerHTML = `${state.aiRecommendation ? resultCard(state.aiRecommendation, 0, true) : ""}${results.map((item, index) => resultCard(item, index, false)).join("")}`;
  list.querySelectorAll(".result-card").forEach((card) => {
    const id = Number(card.dataset.id);
    card.addEventListener("click", (event) => {
      if (event.target.closest("button")) return;
      const result = [state.aiRecommendation, ...state.results].filter(Boolean).find((item) => item.id === id);
      if (result) {
        state.map.setView([result.latitude, result.longitude], 17);
      }
    });
    card.querySelector(".detail-action").addEventListener("click", () => openDetail(id));
    card.querySelector(".direction-action").addEventListener("click", () => {
      const result = [state.aiRecommendation, ...state.results].filter(Boolean).find((item) => item.id === id);
      window.open(`https://map.kakao.com/link/to/${encodeURIComponent(result.name)},${result.latitude},${result.longitude}`, "_blank", "noopener");
      api("/api/usage-events", { method: "POST", body: JSON.stringify({ restaurant_id: id, event_type: "direction" }) }).catch(() => {});
    });
  });
}

async function openDetail(id) {
  try {
    const detail = await api(`/api/restaurants/${id}`);
    const affiliations = unique(detail.partnerships.map((partnership) => partnership.affiliation));
    const benefits = unique(detail.partnerships.flatMap((partnership) => partnership.benefit_items || [partnership.benefit_text || partnership.benefit_label]));
    const conditions = unique(detail.partnerships.flatMap((partnership) => partnership.benefit_conditions || []));
    $("#modal-content").innerHTML = `<div class="section-kicker">PARTNER DETAIL</div><h3 id="modal-title" class="modal-title">${escapeHtml(detail.name)}</h3><p class="detail-sub">${escapeHtml(detail.category)} · ${escapeHtml(detail.address)}</p><div class="store-summary"><div class="content-label">AI 가게 요약</div><p>${escapeHtml(detail.ai_store_summary || detail.menu_summary || "매장 정보가 준비 중입니다.")}</p></div><div class="detail-section"><h4>제휴 혜택</h4>${listHtml(benefits)}</div><div class="detail-section"><h4>적용 대상</h4><div class="eligibility-chips">${affiliations.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>${conditions.length ? `<h4 class="conditions-title">이용 조건</h4>${listHtml(conditions, "condition-list")}` : ""}</div><div class="detail-grid"><div class="detail-item">영업시간<strong>${escapeHtml(detail.opening_hours || "정보 없음")}</strong></div><div class="detail-item">전화번호<strong>${escapeHtml(detail.phone || "정보 없음")}</strong></div><div class="detail-item">대표 메뉴<strong>${escapeHtml(detail.menu_summary || "정보 없음")}</strong></div><div class="detail-item">평균 별점<strong>★ ${Number(detail.rating_average || 0).toFixed(1)} (${detail.review_count}개)</strong></div></div><div class="detail-section"><h4>리뷰</h4>${detail.reviews.map((review) => `<div class="review-item"><strong>★ ${review.rating} · ${escapeHtml(review.author_name)}</strong><p>${escapeHtml(review.content)}</p></div>`).join("") || '<p class="detail-sub">아직 리뷰가 없습니다.</p>'}</div><div class="detail-section"><h4>리뷰 작성</h4><form class="inline-form" id="review-form"><select name="rating" aria-label="별점"><option value="5">★★★★★</option><option value="4">★★★★</option><option value="3">★★★</option><option value="2">★★</option><option value="1">★</option></select><input name="author_name" placeholder="닉네임(선택)" /><textarea name="content" placeholder="제휴 이용 후기를 남겨주세요" required></textarea><button class="button button-primary" type="submit">리뷰 등록</button></form></div><div class="detail-section"><h4>정보 신고</h4><form class="inline-form" id="report-form"><select name="report_type" aria-label="신고 유형"><option value="benefit">혜택 오류</option><option value="location">위치 오류</option><option value="false_info">허위 정보</option></select><textarea name="content" placeholder="확인한 내용을 알려주세요" required></textarea><button class="card-action" type="submit">신고하기</button></form></div>`;
    $("#review-form textarea[name=content]").removeAttribute("required");
    $("#detail-modal").hidden = false;
    api("/api/usage-events", { method: "POST", body: JSON.stringify({ restaurant_id: id, event_type: "view" }) }).catch(() => {});
    $("#review-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(event.target);
      try {
        await api("/api/reviews", { method: "POST", body: JSON.stringify({ restaurant_id: id, rating: Number(data.get("rating")), author_name: data.get("author_name") || "익명", content: data.get("content") }) });
        toast("리뷰가 등록됐어요.");
        openDetail(id);
      } catch (error) { toast(error.message); }
    });
    $("#report-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(event.target);
      try {
        await api("/api/reports", { method: "POST", body: JSON.stringify({ restaurant_id: id, report_type: data.get("report_type"), content: data.get("content") }) });
        toast("신고가 접수됐어요.");
        event.target.reset();
      } catch (error) { toast(error.message); }
    });
  } catch (error) { toast(error.message); }
}

async function calculate(event) {
  event?.preventDefault();
  const myId = Number($("#my-affiliation").value);
  if (!myId) { toast("내 소속을 선택해 주세요."); return; }
  const groups = [{ affiliation_id: myId, count: 1 }, ...[...document.querySelectorAll("#companions .companion-row")].map((row) => ({ affiliation_id: Number(row.querySelector("select").value), count: Number(row.querySelector("input").value || 1) })).filter((group) => group.affiliation_id)];
  const payload = { location: state.location, category: document.querySelector(".nav-filter.active")?.dataset.category || "전체", budget_per_person: FIXED_BUDGET, max_distance_m: null, payment_method: $("#payment").value || null, groups };
  const button = $(".calculate-button");
  button.disabled = true;
  button.textContent = "추천을 계산하는 중...";
  try {
    const data = await api("/api/recommendations", { method: "POST", body: JSON.stringify(payload) });
    state.aiRecommendation = data.ai_recommendation;
    state.results = data.results;
    $("#default-location-banner").hidden = !data.used_default_location;
    renderResults();
    refreshMap([state.aiRecommendation, ...state.results].filter(Boolean));
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; button.innerHTML = "<span>✦</span> 최적 혜택 계산하기"; }
}

async function initGoogleAuth() {
  const button = $("#google-login");
  if (!button) return;
  try {
    const config = await api("/api/v1/auth/config");
    if (!config.enabled || !window.supabase?.createClient) {
      button.textContent = "Google 로그인 준비 중";
      button.disabled = true;
      return;
    }
    state.supabase = window.supabase.createClient(config.supabase_url, config.supabase_anon_key);
    const syncUser = async (session) => {
      state.user = session?.user || null;
      button.textContent = state.user ? `${state.user.user_metadata?.name || state.user.email || "사용자"} · 로그아웃` : "Google 로그인";
      if (session?.access_token) await api("/api/v1/auth/sync", { method: "POST", body: JSON.stringify({ access_token: session.access_token }) });
    };
    state.supabase.auth.onAuthStateChange((_event, session) => { void syncUser(session).catch(() => toast("로그인 사용자 저장에 실패했어요.")); });
    const { data } = await state.supabase.auth.getSession();
    await syncUser(data.session);
    button.addEventListener("click", async () => {
      if (state.user) { await state.supabase.auth.signOut(); return; }
      const { error } = await state.supabase.auth.signInWithOAuth({ provider: "google", options: { redirectTo: window.location.origin } });
      if (error) toast(error.message);
    });
  } catch { button.textContent = "Google 로그인 준비 중"; button.disabled = true; }
}

async function boot() {
  try {
    state.affiliations = await api("/api/affiliations");
    $("#my-affiliation").insertAdjacentHTML("beforeend", affiliationOptions(false));
  } catch (error) { toast("소속 정보를 불러오지 못했습니다."); }
  initMap();
  void initGoogleAuth();
  $("#add-companion").addEventListener("click", addCompanion);
  $("#condition-form").addEventListener("submit", calculate);
  $("#use-location").addEventListener("click", () => {
    if (!navigator.geolocation) { toast("브라우저가 위치 기능을 지원하지 않아 기본 위치를 사용합니다."); return; }
    navigator.geolocation.getCurrentPosition((position) => {
      state.location = { lat: position.coords.latitude, lng: position.coords.longitude, source: "gps" };
      $("#location-status").textContent = "현재 위치를 사용 중이에요.";
      $("#default-location-banner").hidden = true;
      state.map.setView([state.location.lat, state.location.lng], 15);
      state.userMarker.setLatLng([state.location.lat, state.location.lng]);
    }, () => toast("위치를 불러오지 못해 광운대학교 중심 위치를 사용합니다."), { enableHighAccuracy: false, timeout: 7000 });
  });
  document.querySelectorAll(".nav-filter").forEach((button) => button.addEventListener("click", () => {
    document.querySelectorAll(".nav-filter").forEach((node) => node.classList.remove("active"));
    button.classList.add("active");
    if (state.results.length) calculate();
  }));
  $("#sort").addEventListener("change", (event) => {
    const key = event.target.value;
    const lookup = { cdi: "cdi", benefit: "benefit_score", distance: "distance_m", rating: "satisfaction_score" };
    const field = lookup[key];
    state.results.sort((a, b) => key === "distance" ? a[field] - b[field] : b[field] - a[field]);
    renderResults();
    refreshMap([state.aiRecommendation, ...state.results].filter(Boolean));
  });
  document.querySelectorAll("[data-close-modal]").forEach((node) => node.addEventListener("click", () => { $("#detail-modal").hidden = true; }));
  updateSummary();
}

boot();
