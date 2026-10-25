import type { Session } from "./types";
let csrf = "";
export class ApiError extends Error {
  status: number;
  payload: Record<string, unknown>;
  constructor(status: number, payload: Record<string, unknown>) {
    const detail =
      payload.error || payload.message || "Request could not be completed";
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.payload = payload;
  }
}
export function setSession(session: Session) {
  csrf = session.csrf_token || "";
}
export async function api<T>(
  path: string,
  method = "GET",
  data?: unknown,
  revision?: number,
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") headers["X-CSRFToken"] = csrf;
  if (revision !== undefined) headers["If-Match"] = String(revision);
  const body =
    data instanceof FormData
      ? data
      : data === undefined
        ? undefined
        : JSON.stringify(data);
  if (body && !(data instanceof FormData))
    headers["Content-Type"] = "application/json";
  const response = await fetch("/api/studio/" + path.replace(/^\//, ""), {
    method,
    headers,
    body,
    credentials: "same-origin",
    cache: "no-store",
  });
  const payload = await response
    .json()
    .catch(() => ({ error: `Server returned ${response.status}` }));
  if (!response.ok) throw new ApiError(response.status, payload);
  return payload as T;
}
export function errorText(error: unknown) {
  if (
    error instanceof ApiError &&
    (error.status === 409 || error.status === 412)
  )
    return "Draft berubah di sesi lain. Perubahan lokal masih ada. Muat versi server sebelum menyimpan kembali.";
  return error instanceof Error
    ? error.message
    : "Tidak dapat menyelesaikan permintaan.";
}
export const shorten = (value?: string, n = 12) =>
  value ? value.slice(0, n) : "—";
export const formatDate = (value?: string) =>
  value
    ? new Intl.DateTimeFormat("id-ID", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "Asia/Jakarta",
      }).format(new Date(value)) + " WIB"
    : "—";
export function assetURL(
  id: string | null | undefined,
  assets: import("./types").Asset[],
) {
  if (!id) return "";
  return (
    assets.find((x) => x.id === id)?.preview_url ||
    assets.find((x) => x.id === id)?.url ||
    (id.startsWith("/") ? id : "")
  );
}
