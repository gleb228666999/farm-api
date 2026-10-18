import { NextRequest, NextResponse } from "next/server";

/**
 * Прокси к Farm Server (FastAPI на сервере хозяина).
 * Обход CORS: браузер стучится в наш /api/farm, а мы уже — на сервер фермы.
 *
 * POST /api/farm
 * body: {
 *   base:   "http://1.2.3.4:8000"      — базовый URL сервера фермы
 *   method: "GET" | "POST" | "DELETE"
 *   path:   "/api/devices"             — путь на сервере фермы
 *   query?: { device_id: "..." }       — query-параметры
 *   body?:  { ... }                    — JSON-тело (для POST)
 *   timeout?: 30                       — сек (по умолчанию 15)
 * }
 */

export type FarmProxyRequest = {
  base?: string;
  method?: string;
  path?: string;
  query?: Record<string, string | number | undefined>;
  body?: unknown;
  timeout?: number;
};

function normalizeBase(raw: string): string {
  let b = (raw || "").trim();
  if (!b) return "";
  if (!/^https?:\/\//i.test(b)) b = "http://" + b;
  return b.replace(/\/+$/, "");
}

export async function POST(req: NextRequest) {
  let reqBody: FarmProxyRequest;
  try {
    reqBody = (await req.json()) as FarmProxyRequest;
  } catch {
    return NextResponse.json(
      { ok: false, error: "битый JSON в запросе к /api/farm" },
      { status: 400 },
    );
  }

  const base = normalizeBase(reqBody.base || "");
  const method = (reqBody.method || "GET").toUpperCase();
  const path = (reqBody.path || "").startsWith("/")
    ? reqBody.path!
    : "/" + (reqBody.path || "");
  const timeoutSec = Math.min(Math.max(reqBody.timeout ?? 15, 1), 180);

  if (!base) {
    return NextResponse.json(
      { ok: false, error: "не указан адрес сервера фермы (base)" },
      { status: 400 },
    );
  }

  const url = new URL(base + path);
  for (const [k, v] of Object.entries(reqBody.query || {})) {
    if (v !== undefined && v !== null && String(v) !== "") {
      url.searchParams.set(k, String(v));
    }
  }

  const started = Date.now();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutSec * 1000);

  try {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (reqBody.body !== undefined && method !== "GET") {
      headers["Content-Type"] = "application/json";
    }

    const init: RequestInit = {
      method,
      signal: controller.signal,
      headers,
      cache: "no-store",
    };
    if (reqBody.body !== undefined && method !== "GET") {
      init.body = JSON.stringify(reqBody.body);
    }

    const res = await fetch(url.toString(), init);
    const ms = Date.now() - started;
    const text = await res.text();

    let data: unknown = text;
    try {
      data = JSON.parse(text);
    } catch {
      /* не JSON — оставляем текст (например, HTML ошибки) */
    }

    return NextResponse.json({
      ok: res.ok,
      status: res.status,
      ms,
      url: url.toString(),
      data,
      error: res.ok ? null : `HTTP ${res.status}`,
    });
  } catch (e) {
    const ms = Date.now() - started;
    const msg =
      e instanceof Error
        ? e.name === "AbortError"
          ? `таймаут ${timeoutSec}с — сервер не ответил`
          : e.message
        : String(e);
    return NextResponse.json({
      ok: false,
      status: 0,
      ms,
      url: url.toString(),
      data: null,
      error: msg,
    });
  } finally {
    clearTimeout(timer);
  }
}
