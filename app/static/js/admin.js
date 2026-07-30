import { api } from "./api.js";

const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
let affiliations = [];
let partnershipsById = new Map();

function toast(message) {
  const node = $("#admin-toast");
  node.textContent = message;
  node.classList.add("show");
  setTimeout(() => node.classList.remove("show"), 2600);
}

function flat(nodes, depth = 0) {
  return nodes.flatMap((node) => [{ ...node, depth }, ...flat(node.children || [], depth + 1)]);
}

function affiliationOptions() {
  const flattened = flat(affiliations).filter((item) => item.type !== "university");
  return [...flattened.filter((item) => item.name === "전체"), ...flattened.filter((item) => item.name !== "전체")].map((item) => `<option value="${item.id}">${item.name === "전체" ? "" : "　".repeat(item.depth)}${escapeHtml(item.name)}</option>`).join("");
}

function statusBadge(status) {
  const label = { active: "운영 중", pending: "승인 대기", ended: "종료", rejected: "거절" }[status] || status;
  return `<span class="status-badge status-${status}">${label}</span>`;
}

function reviewBadge(item) {
  return item.benefit_needs_review ? '<span class="status-badge status-pending">혜택 확인 필요</span>' : '';
}

async function showDashboard() {
  const data = await api("/api/admin/dashboard");
  $("#view-dashboard").innerHTML = `<div class="dashboard-grid"><div class="stat-card"><span class="stat-icon">▤</span><div class="stat-label">운영 중인 제휴</div><div class="stat-value">${data.active_partnerships}</div><div class="stat-meta">현재 유효한 제휴</div></div><div class="stat-card"><span class="stat-icon">◷</span><div class="stat-label">승인 대기</div><div class="stat-value">${data.pending_partnerships}</div><div class="stat-meta">검토가 필요한 항목</div></div><div class="stat-card"><span class="stat-icon">⌁</span><div class="stat-label">누적 조회</div><div class="stat-value">${data.views.toLocaleString()}</div><div class="stat-meta">전체 업체 상세 조회</div></div><div class="stat-card"><span class="stat-icon">⚑</span><div class="stat-label">미처리 신고</div><div class="stat-value">${data.open_reports}</div><div class="stat-meta">확인이 필요한 신고</div></div></div><div class="admin-card"><h3 class="section-title">운영 알림</h3><div class="alert-list"><div class="alert-item"><span>30일 내 만료 예정 제휴</span>${data.expiring_partnerships ? `<strong class="status-badge status-pending">${data.expiring_partnerships}건</strong>` : '<span class="status-badge status-active">없음</span>'}</div><div class="alert-item"><span>실제 이용 인증</span><strong>${data.verified_uses.toLocaleString()}건</strong></div><div class="alert-item"><span>평균 별점</span><strong>★ ${data.average_rating.toFixed(2)}</strong></div></div></div>`;
}

function partnershipRows(items) {
  return items.map((item) => {
    const benefit = item.benefit_display?.length ? item.benefit_display.join("\n") : (item.benefit_text || item.benefit_label || "제휴 혜택");
    return `<tr><td>${item.status === "pending" ? `<input class="partnership-check bulk-checkbox" type="checkbox" data-id="${item.id}" aria-label="${escapeHtml(item.restaurant_name)} 선택" />` : ""}</td><td><strong>${escapeHtml(item.restaurant_name)}</strong><br /><span style="color:#8b959e">${escapeHtml(item.address)}</span></td><td>${escapeHtml(item.category)}</td><td>${escapeHtml(item.affiliation)}</td><td class="benefit-cell" style="white-space:normal;line-height:1.55;min-width:180px;color:#15263a;font-weight:600">${escapeHtml(benefit).replace(/\n/g, "<br />")}<br />${reviewBadge(item)}</td><td>${item.start_date} ~ ${item.end_date}</td><td>${statusBadge(item.status)}</td><td>${item.benefit_needs_review ? `<button class="table-action review-benefit" data-id="${item.id}">혜택 검토</button>` : ""}<button class="table-action approve" data-id="${item.id}">승인</button><button class="table-action end" data-id="${item.id}">종료</button></td></tr>`;
  }).join("") || '<tr><td colspan="8" style="text-align:center;color:#8b959e">등록된 제휴가 없습니다.</td></tr>';
}

function bindPartnershipActions() {
  document.querySelectorAll(".review-benefit").forEach((button) => button.addEventListener("click", async () => {
    const item = partnershipsById.get(Number(button.dataset.id));
    if (!item) return;
    const analysis = item.benefit_ai_json || {};
    const defaultConditions = analysis.conditions?.join(" / ") || item.benefit_review_note || "";
    const scoreText = window.prompt("관리자가 확정할 혜택 점수(B)를 0~100으로 입력하세요.", String(item.benefit_score_cached || 0));
    if (scoreText === null) return;
    const score = Number(scoreText);
    if (!Number.isFinite(score) || score < 0 || score > 100) return toast("혜택 점수는 0~100 사이 숫자여야 합니다.");
    const conditions = window.prompt("확정된 이용 조건을 / 로 구분해 입력하세요.", defaultConditions);
    if (conditions === null) return;
    const updatedAnalysis = { ...analysis, conditions: conditions.split("/").map((value) => value.trim()).filter(Boolean), conditionCount: conditions.split("/").map((value) => value.trim()).filter(Boolean).length, unknownBenefits: [], unknownConditions: [], needsReview: false, benefitScore: score };
    try {
      await api(`/api/admin/partnerships/${item.id}`, { method: "PUT", body: JSON.stringify({ benefit_ai_json: updatedAnalysis, eligibility_description: conditions, benefit_score_cached: score, benefit_needs_review: false, benefit_review_note: "" }) });
      toast("혜택 점수와 조건을 저장했습니다.");
      await showPartnerships();
    } catch (error) { toast(error.message); }
  }));
  document.querySelectorAll(".approve").forEach((button) => button.addEventListener("click", async () => {
    await api(`/api/admin/partnerships/${button.dataset.id}`, { method: "PUT", body: JSON.stringify({ status: "active" }) });
    toast("제휴를 승인했습니다.");
    showPartnerships();
  }));
  document.querySelectorAll(".end").forEach((button) => button.addEventListener("click", async () => {
    await api(`/api/admin/partnerships/${button.dataset.id}`, { method: "DELETE" });
    toast("제휴를 종료했습니다.");
    showPartnerships();
  }));
}

async function showPartnerships() {
  const data = await api("/api/admin/partnerships");
  partnershipsById = new Map(data.items.map((item) => [item.id, item]));
  $("#view-partnerships").innerHTML = `<div class="toolbar"><div class="toolbar-left"><input id="partnership-search" placeholder="업체명 검색" /><select id="status-filter"><option value="all">전체 상태</option><option value="pending">승인 대기</option><option value="active">운영 중</option><option value="ended">종료</option></select><button id="export-csv" class="outline-button">CSV 다운로드</button></div><div class="toolbar-left"><button class="primary-button" id="bulk-approve" disabled>선택 항목 일괄 승인</button><button class="primary-button" id="go-new">+ 신규 제휴</button></div></div><div class="admin-card table-card"><table class="admin-table"><thead><tr><th><input id="select-all-partnerships" class="bulk-checkbox" type="checkbox" aria-label="승인 대기 전체 선택" /></th><th>업체명</th><th>카테고리</th><th>대상 소속</th><th>혜택</th><th>기간</th><th>상태</th><th>관리</th></tr></thead><tbody id="partnership-rows">${partnershipRows(data.items)}</tbody></table></div>`;
  const renderRows = (items) => { items.forEach((item) => partnershipsById.set(item.id, item)); $("#partnership-rows").innerHTML = partnershipRows(items); bindPartnershipActions(); wireBulkRows(); addPlaceRefreshButtons(); };
  const wireBulkRows = () => {
    const boxes = [...document.querySelectorAll(".partnership-check")];
    const selectAll = $("#select-all-partnerships");
    const bulkButton = $("#bulk-approve");
    const update = () => {
      const selected = boxes.filter((box) => box.checked);
      bulkButton.disabled = selected.length === 0;
      bulkButton.textContent = selected.length ? `선택 항목 일괄 승인 (${selected.length})` : "선택 항목 일괄 승인";
      selectAll.checked = boxes.length > 0 && selected.length === boxes.length;
    };
    boxes.forEach((box) => box.addEventListener("change", update));
    update();
  };
  $("#go-new").addEventListener("click", () => navigate("new"));
  $("#export-csv").addEventListener("click", () => { window.location.href = "/api/admin/partnerships/export"; });
  $("#status-filter").addEventListener("change", async (event) => { const filtered = await api(`/api/admin/partnerships?status=${event.target.value}`); renderRows(filtered.items); });
  $("#partnership-search").addEventListener("input", async (event) => { const filtered = await api(`/api/admin/partnerships?search=${encodeURIComponent(event.target.value)}`); renderRows(filtered.items); });
  $("#select-all-partnerships").addEventListener("change", (event) => { boxesForSelection().forEach((box) => { box.checked = event.target.checked; }); $("#bulk-approve").disabled = !event.target.checked || !boxesForSelection().length; $("#bulk-approve").textContent = event.target.checked ? `선택 항목 일괄 승인 (${boxesForSelection().length})` : "선택 항목 일괄 승인"; });
  $("#bulk-approve").addEventListener("click", async () => {
    const ids = [...document.querySelectorAll(".partnership-check:checked")].map((box) => Number(box.dataset.id));
    if (!ids.length) return;
    try { const result = await api("/api/admin/partnerships/bulk-approve", { method: "POST", body: JSON.stringify({ partnership_ids: ids }) }); toast(`${result.approved}건을 일괄 승인했습니다.`); await showPartnerships(); } catch (error) { toast(error.message); }
  });
  bindPartnershipActions();
  wireBulkRows();
}

function boxesForSelection() { return [...document.querySelectorAll(".partnership-check")]; }

function addPlaceRefreshButtons() {
  document.querySelectorAll("#partnership-rows tr").forEach((row) => {
    const actionCell = row.lastElementChild;
    const existingAction = actionCell?.querySelector("[data-id]");
    if (!actionCell || !existingAction || actionCell.querySelector(".refresh-place")) return;
    const button = document.createElement("button");
    button.className = "table-action refresh-place";
    button.dataset.id = existingAction.dataset.id;
    button.textContent = "정보 새로고침";
    button.addEventListener("click", async () => {
      try {
        await api(`/api/admin/places/${button.dataset.id}/refresh`, { method: "POST" });
        toast("장소 정보를 새로고침했습니다.");
        await showPartnerships();
        addPlaceRefreshButtons();
      } catch (error) { toast(error.message); }
    });
    actionCell.appendChild(button);
  });
}

function showNew() {
  {
    $("#view-new").innerHTML = `<div class="admin-card form-card"><h3 class="section-title">신규 제휴 등록</h3><p class="helper">가게 정보 검색은 이 화면에서만 외부 장소 API를 1회 호출합니다. 검색 결과를 선택하면 주소·좌표·전화번호가 자동 입력됩니다.</p><form id="new-partnership-form"><div class="form-grid"><div class="form-field full"><label>가게 이름</label><div style="display:flex;gap:8px"><input name="restaurant_name" required placeholder="예: 새식당" style="flex:1" /><button id="search-place" class="outline-button" type="button">가게 정보 검색</button></div><div id="place-search-results" style="display:grid;gap:8px;margin-top:10px"></div><input type="hidden" name="restaurant_id" /><input type="hidden" name="place_id" /><input type="hidden" name="place_provider" /></div><div class="form-field"><label>카테고리</label><input name="category" value="식사류" required /></div><div class="form-field"><label>주소</label><input name="address" placeholder="검색 결과에서 자동 입력" /></div><div class="form-field"><label>전화번호</label><input name="phone" /></div><div class="form-field"><label>위도</label><input name="latitude" type="number" step="any" value="37.6194" required /></div><div class="form-field"><label>경도</label><input name="longitude" type="number" step="any" value="127.0597" required /></div><div class="form-field"><label>영업시간</label><input name="opening_hours" placeholder="선택 입력" /></div><div class="form-field"><label>대표 메뉴/설명</label><input name="menu_summary" placeholder="선택 입력" /></div><div class="form-field full"><label>제휴 대상 소속</label><select name="affiliation_ids" multiple size="5" required>${affiliationOptions()}</select><p class="helper">Ctrl/Cmd를 눌러 여러 소속을 선택할 수 있습니다.</p></div><div class="form-field full"><label>제휴 혜택 원문</label><textarea name="benefit_text" placeholder="예: 학생증 제시 시 평일 오후 2시 이후 음료 1잔 무료" required></textarea><div style="display:flex;align-items:center;gap:10px;margin-top:8px"><button id="analyze-benefit" class="outline-button" type="button">AI 혜택 분석</button><span class="helper">분석 결과를 확인·수정한 뒤 저장할 수 있습니다.</span></div><pre id="benefit-analysis-preview" style="white-space:pre-wrap;background:#faf7f2;padding:10px;border-radius:8px;display:none"></pre></div><div class="form-field"><label>혜택 유형</label><select name="benefit_type"><option value="percentage">비율 할인</option><option value="fixed">정액 할인</option><option value="service">서비스 제공</option><option value="discount">기타 혜택</option></select></div><div class="form-field"><label>적용 범위</label><select name="application_scope"><option value="ALL_GROUP">일행 전체 적용</option><option value="ELIGIBLE_MEMBERS_ONLY">대상자에게만 적용</option><option value="ONCE_PER_ORDER">주문당 1회 적용</option></select></div><div class="form-field"><label>할인율 (%)</label><input name="discount_rate" type="number" min="0" max="100" value="0" /></div><div class="form-field"><label>정액 할인 (원)</label><input name="fixed_discount" type="number" min="0" value="0" /></div><div class="form-field"><label>서비스 품목</label><input name="service_item" placeholder="무료 음료 1잔" /></div><div class="form-field"><label>추정 현금 가치 (원)</label><input name="estimated_cash_value" type="number" min="0" value="0" /></div><div class="form-field"><label>최소 주문 금액 (원)</label><input name="min_order_amount" type="number" min="0" value="0" /></div><div class="form-field"><label>최소 인원</label><input name="min_people" type="number" min="1" value="1" /></div><div class="form-field"><label>결제 방식</label><input name="payment_method" placeholder="예: 카드 가능" /></div><div class="form-field"><label>인증 방법</label><input name="verification_method" value="학생증 또는 모바일 학생증" /></div><div class="form-field"><label>시작일</label><input name="start_date" type="date" required /></div><div class="form-field"><label>종료일</label><input name="end_date" type="date" required /></div><div class="form-field full"><label>자격 및 메모</label><textarea name="eligibility_description" placeholder="제휴 상세 조건"></textarea></div></div><div class="form-actions"><button class="primary-button" type="submit">저장 및 승인 요청</button></div></form></div>`;
    const form = $("#new-partnership-form");
    const analysisPreview = $("#benefit-analysis-preview");
    analysisPreview.contentEditable = "true";
    form.benefit_text.addEventListener("input", () => { analysisPreview.textContent = ""; analysisPreview.style.display = "none"; });
    form.start_date.value = new Date().toISOString().slice(0, 10);
    form.end_date.value = new Date(Date.now() + 180 * 86400000).toISOString().slice(0, 10);
    for (const key of ["latitude", "longitude"]) {
      form.elements[key].value = "";
      form.elements[key].removeAttribute("required");
    }
    form.elements.longitude.closest(".form-field")?.insertAdjacentHTML("beforeend", '<p class="helper">가게 정보 검색 결과를 선택하면 주소와 좌표가 자동 입력됩니다. 입력하지 않아도 저장 시 카카오 검색으로 자동 보완합니다.</p>');
    const fillPlace = (item) => {
      for (const key of ["name", "category", "address", "phone", "opening_hours", "image_url", "latitude", "longitude"]) if (form.elements[key] && item[key] != null) form.elements[key].value = item[key];
      form.restaurant_id.value = item.restaurant_id || "";
      form.place_id.value = item.place_id || "";
      form.place_provider.value = item.place_provider || "";
      $("#place-search-results").innerHTML = `<p class="helper">선택됨: ${escapeHtml(item.name)} · ${escapeHtml(item.address || "주소 정보 없음")}</p>`;
    };
    $("#search-place").addEventListener("click", async () => {
      const query = form.restaurant_name.value.trim();
      if (!query) return toast("가게명을 먼저 입력해 주세요.");
      try {
        const data = await api(`/api/admin/places/search?q=${encodeURIComponent(query)}`);
        const items = data.items || [];
        $("#place-search-results").innerHTML = items.length ? items.map((item, index) => `<button type="button" class="outline-button place-result" data-index="${index}" style="text-align:left"><strong>${escapeHtml(item.name)}</strong> · ${escapeHtml(item.category)}<br /><small>${escapeHtml(item.address || "주소 정보 없음")} · ${escapeHtml(item.phone || "전화번호 없음")}</small></button>`).join("") : '<p class="helper">검색 결과가 없습니다. 주소와 좌표를 직접 입력할 수 있습니다.</p>';
        document.querySelectorAll(".place-result").forEach((button) => button.addEventListener("click", () => fillPlace(items[Number(button.dataset.index)])));
      } catch (error) { toast(error.message); }
    });
    $("#analyze-benefit").addEventListener("click", async () => {
      const benefitText = form.benefit_text.value.trim();
      if (!benefitText) return toast("혜택 원문을 먼저 입력해 주세요.");
      try {
        const result = await api("/api/admin/ai/analyze-benefit", { method: "POST", body: JSON.stringify({ benefit_text: benefitText }) });
        const analysis = result.analysis || {};
        form.dataset.benefitAnalysis = JSON.stringify(analysis);
        const rate = Number(analysis.discountRate || 0);
        const amount = Number(analysis.discountAmount || 0);
        form.discount_rate.value = rate;
        form.fixed_discount.value = amount;
        form.service_item.value = analysis.freeItem || "";
        form.min_order_amount.value = Number(analysis.minimumOrder || 0);
        form.min_people.value = Number(analysis.requiredPeople || 1);
        form.eligibility_description.value = (analysis.conditions || []).join(" / ");
        if (analysis.studentVerification) form.verification_method.value = "학생증 제시";
        form.benefit_type.value = rate ? "percentage" : amount ? "fixed" : analysis.freeItem ? "service" : "discount";
        analysisPreview.textContent = JSON.stringify(analysis, null, 2);
        analysisPreview.style.display = "block";
      } catch (error) { toast(error.message); }
    });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(form);
      const body = Object.fromEntries(data.entries());
      body.affiliation_ids = [...form.querySelector("[name=affiliation_ids]").selectedOptions].map((option) => Number(option.value));
      for (const key of ["latitude", "longitude", "discount_rate", "fixed_discount", "estimated_cash_value", "min_order_amount", "min_people"]) body[key] = Number(body[key] || 0);
      body.restaurant_id = Number(body.restaurant_id || 0) || null;
      try { body.benefit_ai_json = analysisPreview.textContent.trim() ? JSON.parse(analysisPreview.textContent) : {}; } catch { return toast("AI 분석 JSON 형식을 확인해 주세요."); }
      try { await api("/api/admin/partnerships", { method: "POST", body: JSON.stringify(body) }); toast("제휴를 저장했습니다."); navigate("partnerships"); } catch (error) { toast(error.message); }
    });
    return;
  }
  $("#view-new").innerHTML = `<div class="admin-card form-card"><h3 class="section-title">신규 제휴 등록</h3><form id="new-partnership-form"><div class="form-grid"><div class="form-field"><label>업체명</label><input name="restaurant_name" required placeholder="예: 새식당" /></div><div class="form-field"><label>카테고리</label><select name="category"><option>식사류</option><option>카페/디저트</option><option>주점</option><option>기타</option></select></div><div class="form-field"><label>주소</label><input name="address" placeholder="서울 노원구 ..." /></div><div class="form-field"><label>전화번호</label><input name="phone" /></div><div class="form-field"><label>위도</label><input name="latitude" type="number" step="any" value="37.6194" required /></div><div class="form-field"><label>경도</label><input name="longitude" type="number" step="any" value="127.0597" required /></div><div class="form-field"><label>영업시간</label><input name="opening_hours" placeholder="11:00–21:00" /></div><div class="form-field"><label>대표 메뉴/설명</label><input name="menu_summary" placeholder="대표 메뉴와 매장 특징" /></div><div class="form-field full"><label>제휴 대상 소속</label><select name="affiliation_ids" multiple size="5" required>${affiliationOptions()}</select><p class="helper">Ctrl/Cmd를 눌러 여러 소속을 선택할 수 있습니다.</p></div><div class="form-field"><label>혜택 유형</label><select name="benefit_type"><option value="percentage">비율 할인</option><option value="fixed">정액 할인</option><option value="service">서비스 제공</option></select></div><div class="form-field"><label>적용 범위</label><select name="application_scope"><option value="ALL_GROUP">일행 전체 적용</option><option value="ELIGIBLE_MEMBERS_ONLY">대상자에게만 적용</option><option value="ONCE_PER_ORDER">주문당 1회 적용</option></select></div><div class="form-field"><label>할인율 (%)</label><input name="discount_rate" type="number" min="0" max="100" value="0" /></div><div class="form-field"><label>정액 할인 (원)</label><input name="fixed_discount" type="number" min="0" value="0" /></div><div class="form-field"><label>서비스 품목</label><input name="service_item" placeholder="무료 음료 1잔" /></div><div class="form-field"><label>추정 현금 가치 (원)</label><input name="estimated_cash_value" type="number" min="0" value="0" /></div><div class="form-field"><label>최소 주문 금액 (원)</label><input name="min_order_amount" type="number" min="0" value="0" /></div><div class="form-field"><label>최소 인원</label><input name="min_people" type="number" min="1" value="1" /></div><div class="form-field"><label>결제 방식</label><select name="payment_method"><option value="">상관없음</option><option>카드</option><option>현금</option><option>간편결제</option></select></div><div class="form-field"><label>인증 방법</label><input name="verification_method" value="학생증 또는 모바일 학생증" /></div><div class="form-field"><label>시작일</label><input name="start_date" type="date" required /></div><div class="form-field"><label>종료일</label><input name="end_date" type="date" required /></div><div class="form-field full"><label>자격 및 메모</label><textarea name="eligibility_description" placeholder="제휴 상세 조건"></textarea></div></div><div class="form-actions"><button class="primary-button" type="submit">저장 및 승인 요청</button></div></form></div>`;
  const form = $("#new-partnership-form");
  form.querySelector(".form-grid").insertAdjacentHTML("afterbegin", '<div class="form-field full"><label>제휴 혜택 원문</label><textarea name="benefit_text" placeholder="예: 학생증 제시 시 전 메뉴 10% 할인\n음료 1잔 무료 제공" required></textarea><p class="helper">관리자 화면과 사용자 화면에 이 내용이 그대로 표시됩니다.</p></div>');
  form.start_date.value = new Date().toISOString().slice(0, 10);
  form.end_date.value = new Date(Date.now() + 180 * 86400000).toISOString().slice(0, 10);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const body = Object.fromEntries(data.entries());
    body.affiliation_ids = [...form.querySelector("[name=affiliation_ids]").selectedOptions].map((option) => Number(option.value));
    for (const key of ["latitude", "longitude", "discount_rate", "fixed_discount", "estimated_cash_value", "min_order_amount", "min_people"]) body[key] = Number(body[key] || 0);
    try { await api("/api/admin/partnerships", { method: "POST", body: JSON.stringify(body) }); toast("제휴를 저장했습니다."); navigate("partnerships"); } catch (error) { toast(error.message); }
  });
}

function renderImportPreview(data) {
  const rows = data.rows || [];
  $("#import-preview").innerHTML = `<p class="helper">총 ${data.total_count}행 · 유효 ${data.valid_count}행 · 오류 ${data.errors.length}행${data.ai_transformed ? " · AI 변환 완료" : ""}</p><div class="table-card admin-card"><table class="admin-table"><thead><tr><th>업체명</th><th>카테고리</th><th>주소</th><th>제휴대상</th><th>혜택 원문</th><th>기간</th><th>검증</th></tr></thead><tbody>${rows.map((row) => `<tr><td>${escapeHtml(row.restaurant_name)}</td><td>${escapeHtml(row.category)}</td><td>${escapeHtml(row.address)}</td><td>${escapeHtml(row.target_affiliations || row.department || row.college)}</td><td>${escapeHtml(row.benefit_text)}</td><td>${row.start_date || ""} ~ ${row.end_date || ""}</td><td class="${row.errors?.length ? "preview-error" : ""}">${escapeHtml(row.errors?.join(", ") || row.warnings?.join(", ") || "정상")}</td></tr>`).join("")}</tbody></table></div>${data.valid_count ? '<button id="commit-import" class="primary-button" style="margin-top:14px">검증 통과 데이터 저장</button>' : ""}`;
  $("#commit-import")?.addEventListener("click", async () => { try { const result = await api("/api/admin/import/commit", { method: "POST", body: JSON.stringify({ rows }) }); toast(`${result.imported}건을 저장했습니다.`); } catch (error) { toast(error.message); } });
}

async function previewImport(endpoint) {
  const file = $("#import-file").files[0];
  if (!file) { toast("먼저 Excel 파일을 선택하세요."); return; }
  const form = new FormData();
  form.append("file", file);
  try {
    const response = await fetch(endpoint, { method: "POST", body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "파일을 처리하지 못했습니다.");
    renderImportPreview(data);
  } catch (error) { toast(error.message); }
}

function showImport() {
  {
    $("#view-import").innerHTML = `<div class="admin-card"><div class="toolbar"><div><h3 class="section-title">광운대 제휴정보 일괄등록</h3><p class="helper">아래의 지정 양식을 다운로드해 작성한 뒤 업로드하세요. 엑셀 AI 형식 변환은 사용하지 않습니다.</p></div><a class="outline-button" href="/api/v1/admin/import/template">광운대 제휴정보 일괄등록용 다운로드</a></div><div class="ai-note">가게 정보는 등록 화면의 장소 검색에서, 혜택 분석은 혜택 문장 입력 후 AI 혜택 분석에서 처리합니다.</div><div class="file-drop"><div>지정 양식 파일을 선택하세요. xlsx, xls, xlsm, csv 지원</div><input id="import-file" type="file" accept=".xlsx,.xls,.xlsm,.csv" /></div><div class="ai-import-actions"><button id="preview-standard" class="outline-button" type="button">지정 양식 미리보기</button><button id="generate-summaries" class="outline-button" type="button">기존 매장 AI 요약 생성</button><button id="preprocess-benefits" class="outline-button" type="button">전체 혜택 AI 전처리</button></div><div id="import-preview" class="preview-wrap"></div></div>`;
    $("#preview-standard").addEventListener("click", () => previewImport("/api/admin/import/preview"));
    $("#preprocess-benefits").addEventListener("click", async () => { try { const result = await api("/api/admin/ai/preprocess-benefits", { method: "POST" }); toast(`${result.processed}건 전처리 완료 · 확인 필요 ${result.needs_review || 0}건 · 실패 ${result.failed}건`); } catch (error) { toast(error.message); } });
    $("#generate-summaries").addEventListener("click", async () => { try { const result = await api("/api/admin/ai/generate-summaries?force=true", { method: "POST" }); toast(`${result.generated}개 매장 요약을 생성했습니다.`); } catch (error) { toast(error.message); } });
    return;
  }
  $("#view-import").innerHTML = `<div class="admin-card"><div class="toolbar"><div><h3 class="section-title">광운대 제휴정보 일괄등록</h3><p class="helper">원본 Excel은 기본 형식 미리보기 또는 AI 형식 변환을 선택할 수 있습니다.</p></div><a class="outline-button" href="/api/v1/admin/import/template">광운대 제휴정보 일괄등록용 다운로드</a></div><div class="ai-note">AI 변환은 열 이름과 혜택 문장을 표준 형식으로 정리합니다. 변환 결과를 확인한 뒤 저장하세요. GEMINI_API_KEY가 없으면 기본 변환만 사용할 수 있습니다.</div><div class="file-drop"><div>파일을 선택하세요. xlsx, xls, xlsm, csv, txt 지원</div><input id="import-file" type="file" accept=".xlsx,.xls,.xlsm,.csv,.txt" /></div><div class="ai-import-actions"><button id="preview-standard" class="outline-button" type="button">기본 형식으로 미리보기</button><button id="preview-ai" class="primary-button" type="button">AI로 표준 형식 변환</button><button id="generate-summaries" class="outline-button" type="button">기존 매장 AI 요약 생성</button></div><div id="import-preview" class="preview-wrap"></div></div>`;
  $("#preview-standard").addEventListener("click", () => previewImport("/api/admin/import/preview"));
  $(".ai-import-actions").insertAdjacentHTML("beforeend", '<button id="preprocess-benefits" class="outline-button" type="button">전체 혜택 AI 전처리</button>');
  $("#preprocess-benefits").addEventListener("click", async () => { try { const result = await api("/api/admin/ai/preprocess-benefits", { method: "POST" }); toast(`${result.processed}건 전처리 완료 · 확인 필요 ${result.needs_review || 0}건 · 실패 ${result.failed}건`); } catch (error) { toast(error.message); } });
  $("#generate-summaries").addEventListener("click", async () => { try { const result = await api("/api/admin/ai/generate-summaries?force=true", { method: "POST" }); toast(`${result.generated}개 매장 요약을 생성했습니다.`); } catch (error) { toast(error.message); } });
}

async function showReports() {
  const data = await api("/api/admin/reports");
  $("#view-reports").innerHTML = `<div class="admin-card"><h3 class="section-title">리뷰 및 신고 관리</h3>${data.items.map((item) => `<div class="report-card"><div><strong>${escapeHtml(item.restaurant_name)} · ${escapeHtml(item.report_type)}</strong><p>${escapeHtml(item.content)}</p><span class="status-badge ${item.status === "open" ? "status-pending" : "status-active"}">${item.status === "open" ? "미처리" : "처리됨"}</span></div><button class="table-action resolve-report" data-id="${item.id}">${item.status === "open" ? "처리 완료" : "되돌리기"}</button></div>`).join("") || '<p class="helper">접수된 신고가 없습니다.</p>'}</div>`;
  document.querySelectorAll(".resolve-report").forEach((button) => button.addEventListener("click", async () => { await api(`/api/admin/reports/${button.dataset.id}`, { method: "PUT", body: JSON.stringify({ status: "resolved" }) }); toast("신고 상태를 업데이트했습니다."); showReports(); }));
}

async function navigate(view) {
  document.querySelectorAll(".admin-view").forEach((node) => { node.hidden = true; });
  document.querySelectorAll(".side-nav").forEach((node) => node.classList.toggle("active", node.dataset.view === view));
  const titles = { dashboard: "대시보드", new: "신규 제휴 등록", partnerships: "제휴 정보 관리", import: "데이터 일괄 등록", reports: "리뷰 및 신고 관리" };
  $("#page-title").textContent = titles[view];
  const target = $(`#view-${view}`);
  target.hidden = false;
  try {
    if (view === "dashboard") await showDashboard();
    if (view === "new") showNew();
    if (view === "partnerships") { await showPartnerships(); addPlaceRefreshButtons(); }
    if (view === "import") showImport();
    if (view === "reports") await showReports();
  } catch (error) { toast(error.message); }
}

async function boot() {
  try {
    affiliations = await api("/api/affiliations");
    await api("/api/admin/dashboard");
    $("#login-gate").hidden = true;
    $("#admin-content").hidden = false;
    await navigate("dashboard");
  } catch { $("#admin-content").hidden = true; }
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try { await api("/api/admin/login", { method: "POST", body: JSON.stringify({ password: $("#admin-password").value }) }); toast("로그인했습니다."); await boot(); } catch (error) { toast(error.message); }
});
$("#logout").addEventListener("click", async () => { await api("/api/admin/logout", { method: "POST" }); location.reload(); });
document.querySelectorAll(".side-nav").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.view)));
boot();
