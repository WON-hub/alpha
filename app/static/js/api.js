export async function api(path, options = {}) {
  const versionedPath = path.startsWith("/api/") && !path.startsWith("/api/v1/") ? path.replace(/^\/api\//, "/api/v1/") : path;
  const response = await fetch(versionedPath, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "요청을 처리하지 못했습니다.");
  return data;
}
