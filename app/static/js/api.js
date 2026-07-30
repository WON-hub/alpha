function formatApiError(detail, fallback) {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      if (typeof item === "string") return item;
      const location = Array.isArray(item?.loc) ? `${item.loc.join(".")}: ` : "";
      return `${location}${item?.msg || item?.message || JSON.stringify(item)}`;
    }).join(" / ");
  }
  if (detail && typeof detail === "object") return detail.message || detail.error || JSON.stringify(detail);
  return fallback;
}

export async function api(path, options = {}) {
  const versionedPath = path.startsWith("/api/") && !path.startsWith("/api/v1/") ? path.replace(/^\/api\//, "/api/v1/") : path;
  const response = await fetch(versionedPath, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(formatApiError(data.detail, "요청을 처리하지 못했습니다."));
  return data;
}
