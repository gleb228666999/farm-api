"use client";

import { create } from "zustand";
import { toast } from "sonner";
import type { FarmCallResult } from "@/lib/farm-types";

const BASE_KEY = "farm_base_url";

// 🆑 v1.0: дефолтный адрес — ТОТ ЖЕ ХОСТ, с которого открыта панель (панель обычно
// запускают на одной машине с Farm Server). Раньше дефолт был жёстко 127.0.0.1:8000 —
// если панель открыть с телефона/другого ПК, 127.0.0.1 указывал на САМО устройство
// пользователя, сервер «не отвечал», health=down и ВСЕ кнопки были заблокированы
// («кнопки не работают»). Теперь подставляется хост из адресной строки.
function detectDefaultBase(): string {
  if (typeof window === "undefined") return "http://127.0.0.1:8000";
  const h = window.location.hostname;
  if (!h || h === "localhost" || h === "127.0.0.1") return "http://127.0.0.1:8000";
  return `http://${h}:8000`;
}

const DEFAULT_BASE = detectDefaultBase();

export function loadBase(): string {
  if (typeof window === "undefined") return "";
  try {
    return localStorage.getItem(BASE_KEY) || "";
  } catch {
    return "";
  }
}

export function saveBase(v: string) {
  try {
    localStorage.setItem(BASE_KEY, v);
  } catch {
    /* noop */
  }
}

// ---------- журнал действий ----------

export type LogEntry = {
  id: number;
  ts: number;
  label: string;       // человекочитаемое действие («Фарм ⏹ на phone_01»)
  target: string;      // путь API или описание
  ok: boolean | null;  // null = ещё выполняется
  ms: number | null;
  status: number | null;
  result: unknown;     // ответ сервера
  error?: string | null;
};

type FarmState = {
  base: string;
  health: "unknown" | "checking" | "up" | "down";
  healthInfo: string;
  /** 🆑 v0.9: сеть/сервер недоступны (2 неудачи подряд) — фоновые опросы
   *  затихают, чтобы не копить стопку зависших запросов (та самая «лаганина»). */
  netDown: boolean;
  log: LogEntry[];
  busy: Record<string, boolean>; // ключ занятости кнопок
  setBase: (v: string) => void;
  initBase: () => void;
  setHealth: (h: FarmState["health"], info?: string) => void;
  setBusy: (key: string, v: boolean) => void;
  clearLog: () => void;
  sendTask: (opts: {
    label: string;
    deviceId: string | "*";
    task: string;
    payload?: unknown;
    timeout?: number;
    busyKey?: string;
    waitSec?: number; // сколько секунд ждать результат телефона (0 = не ждать)
    /** 🆑 v1.0: "background" (по умолчанию) — ответить СРАЗУ после отправки,
     *  результат телефона догонит тостом + записью в журнал; "inline" — ждать
     *  результат здесь (exec/чтение логов — нужен вывод в диалоге). */
    mode?: "inline" | "background";
  }) => Promise<FarmCallResult>;
  call: <T = unknown>(opts: {
    label: string;
    method?: string;
    path: string;
    query?: Record<string, string | number | undefined>;
    body?: unknown;
    timeout?: number;
    busyKey?: string;
    silent?: boolean; // не писать в журнал (фоновые опросы)
    /** 🆑 v0.9: слить одновременные одинаковые GET в один запрос (для опросов) */
    dedupe?: boolean;
  }) => Promise<FarmCallResult<T>>;
};

let logId = 1;

// 🆑 v1.0: общий цикл ожидания результата телефона. Используется в двух режимах:
//  • background (дефолт) — запускается «в воздух», НЕ блокирует кнопку и тост:
//    пользователь сразу видит «отправлено», а когда телефон ответит — прилетит
//    тост «✅ Результат» + запись в журнал. Раньше всё это ждало ДО 30–60с
//    в самом обработчике кнопки → «кнопка не работает / очень долго отвечает».
//  • inline — exec/чтение логов: результат нужен в диалоге, ждём синхронно.
async function pollForResult(
  taskId: string,
  label: string,
  waitSec: number,
): Promise<unknown | null> {
  const deadline = Date.now() + waitSec * 1000;
  while (Date.now() < deadline) {
    // 3с между опросами — результат обычно приходит за секунды
    await new Promise((r) => setTimeout(r, 3000));
    const rr = await useFarm.getState().call<{ status: string; data?: unknown }>({
      label: `⏳ ожидание результата ${taskId}`,
      method: "GET",
      path: `/api/results/${taskId}`,
      silent: true,
    });
    if (rr.ok && rr.data && (rr.data as { status?: string }).status === "done") {
      const data = (rr.data as { data?: unknown }).data ?? rr.data;
      useFarm.setState((s) => ({
        log: [
          {
            id: logId++,
            ts: Date.now(),
            label: `✅ Результат: ${label}`,
            target: `result ${taskId}`,
            ok: true,
            ms: null,
            status: 200,
            result: data,
          },
          ...s.log,
        ].slice(0, 300),
      }));
      toast.success(`✅ ${label}`, { description: "телефон ответил — подробности в журнале" });
      return data;
    }
  }
  useFarm.setState((s) => ({
    log: [
      {
        id: logId++,
        ts: Date.now(),
        label: `⏳ Результат не пришёл за ${waitSec}с: ${label}`,
        target: `result ${taskId}`,
        ok: false,
        ms: null,
        status: null,
        result: null,
        error: `телефон не ответил за ${waitSec}с — задача ещё может выполниться; проверь вкладку «Результат» (task_id=${taskId}) или журнал`,
      },
      ...s.log,
    ].slice(0, 300),
  }));
  toast.warning(`⏳ ${label}`, {
    description: `телефон не ответил за ${waitSec}с — задача ещё может выполниться`,
  });
  return null;
}

// 🆑 v0.9: дедупликация одновременных одинаковых GET-опросов. Раньше каждые 5с
// уходил новый /api/devices даже пока висел предыдущий (сервер медленный/недоступен
// = 15с таймаут) → запросы громоздились, лимит соединений браузера забивался,
// ВСЕ кнопки стояли в очереди → «всё лагает». Теперь одинаковый опрос,
// пока не закончился предыдущий, переиспользует его промис.
const inflight = new Map<string, Promise<FarmCallResult>>();

// счётчик подряд идущих сетевых неудач (для netDown)
let netFailStreak = 0;

export const useFarm = create<FarmState>((set, get) => ({
  base: "",
  health: "unknown",
  healthInfo: "",
  netDown: false,
  log: [],
  busy: {},

  setBase: (v) => {
    saveBase(v);
    set({ base: v, health: "unknown", healthInfo: "" });
  },

  initBase: () => {
    const b = loadBase() || DEFAULT_BASE;
    if (b) set({ base: b });
  },

  setHealth: (h, info = "") => set({ health: h, healthInfo: info }),

  setBusy: (key, v) =>
    set((s) => {
      const busy = { ...s.busy };
      if (v) busy[key] = true;
      else delete busy[key];
      return { busy };
    }),

  clearLog: () => set({ log: [] }),

  sendTask: async (opts) => {
    const { call } = get();
    const isBroadcast = !opts.deviceId || opts.deviceId === "*";
    const path = isBroadcast
      ? "/api/broadcast"
      : `/api/devices/${opts.deviceId}/send`;
    const body: Record<string, unknown> = { type: "task", task: opts.task };
    if (opts.payload !== undefined && opts.payload !== null) {
      body.payload = opts.payload;
    }

    const res = await call({
      label: opts.label,
      method: "POST",
      path,
      body,
      timeout: opts.timeout ?? 20,
      busyKey: opts.busyKey,
    });
    if (!res.ok) return res;

    // вытащить task_id из ответа сервера
    // (api_broadcast → sent: число, api_groups_send → sent: массив объектов)
    const d = res.data as {
      task_id?: string;
      task_ids?: string[];
      sent?: number | Array<{ device_id?: string; task_id: string }>;
    } | null;
    const taskIds: string[] = [];
    if (d?.task_id) taskIds.push(d.task_id);
    if (d?.task_ids) taskIds.push(...d.task_ids);
    if (Array.isArray(d?.sent)) {
      for (const s of d.sent) if (s?.task_id) taskIds.push(s.task_id);
    }

    const waitSec = opts.waitSec ?? 0;
    const mode = opts.mode || "background";
    if (!taskIds.length || waitSec <= 0 || taskIds.length > 1) return res;

    const taskId = taskIds[0];

    // 🆑 v1.0: background (дефолт) — НЕ держим обработчик кнопки: тост
    // «отправлено» вылетает мгновенно, результат телефона догонит тостом
    // «✅ Результат» и записью в журнал. inline — ждём (exec/логи).
    if (mode === "background") {
      void pollForResult(taskId, opts.label, waitSec);
      return res;
    }

    const data = await pollForResult(taskId, opts.label, waitSec);
    if (data !== null) return { ...res, data };
    return res;
  },

  call: async <T = unknown>(opts) => {
    const { base, setBusy } = get();
    const method = (opts.method || "GET").toUpperCase();

    // 🆑 v0.9: дедупликация фоновых опросов — одинаковый GET, пока предыдущий
    // ещё летит, вернёт тот же промис вместо новой копии запроса
    const dKey =
      opts.dedupe && method === "GET"
        ? `GET ${opts.path} ${JSON.stringify(opts.query || {})}`
        : null;
    if (dKey) {
      const p = inflight.get(dKey);
      if (p) return p as Promise<FarmCallResult<T>>;
    }

    const entry: LogEntry = {
      id: logId++,
      ts: Date.now(),
      label: opts.label,
      target: `${method} ${opts.path}`,
      ok: null,
      ms: null,
      status: null,
      result: null,
    };
    if (!opts.silent) {
      set((s) => ({ log: [entry, ...s.log].slice(0, 300) }));
    }
    const busyKey = opts.busyKey;
    if (busyKey) setBusy(busyKey, true);

    const exec = async (): Promise<FarmCallResult<T>> => {
      try {
        const res = await fetch("/api/farm", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            base,
            method,
            path: opts.path,
            query: opts.query,
            body: opts.body,
            timeout: opts.timeout,
          }),
        });
        const data = (await res.json()) as FarmCallResult<T>;
        // 🆑 v0.9: успех = сеть жива; сетевой сбой = status===0 (прокси не смог
        // достучаться до сервера фермы: сеть/таймаут). HTTP-ошибки (404 и т.п.)
        // сетью не считаются — сервер отвечает, значит связь есть.
        if (data.ok) {
          netFailStreak = 0;
          if (get().netDown) set({ netDown: false });
        } else if (data.status === 0) {
          netFailStreak += 1;
          if (netFailStreak >= 2 && !get().netDown) set({ netDown: true });
        }
        if (!opts.silent) {
          set((s) => ({
            log: s.log.map((l) =>
              l.id === entry.id
                ? {
                    ...l,
                    ok: data.ok,
                    ms: data.ms,
                    status: data.status,
                    result: data.data,
                    error: data.error,
                  }
                : l,
            ),
          }));
        }
        return data;
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        // 🆑 v0.9: сам запрос к /api/farm упал — тоже сетевой сбой
        netFailStreak += 1;
        if (netFailStreak >= 2 && !get().netDown) set({ netDown: true });
        if (!opts.silent) {
          set((s) => ({
            log: s.log.map((l) =>
              l.id === entry.id
                ? { ...l, ok: false, ms: null, status: 0, error: msg }
                : l,
            ),
          }));
        }
        return {
          ok: false,
          status: 0,
          ms: 0,
          data: null,
          error: msg,
        } as FarmCallResult<T>;
      } finally {
        if (busyKey) setBusy(busyKey, false);
        if (dKey) {
          // маленькая задержка: чтобы опросы, пришедшие в ту же секунду,
          // успели переиспользовать промис до его удаления из карты
          setTimeout(() => inflight.delete(dKey), 500);
        }
      }
    };

    const p = exec();
    if (dKey) inflight.set(dKey, p as Promise<FarmCallResult>);
    return p;
  },
}));
