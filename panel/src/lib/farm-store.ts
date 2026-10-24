"use client";

import { create } from "zustand";
import type { FarmCallResult } from "@/lib/farm-types";

const BASE_KEY = "farm_base_url";

// Дефолт: сервер фермы на той же машине (превью/локальный запуск).
// Меняется в шапке панели и сохраняется в localStorage.
const DEFAULT_BASE = "http://127.0.0.1:8000";

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
    if (!taskIds.length || waitSec <= 0 || taskIds.length > 1) return res;

    const taskId = taskIds[0];
    const deadline = Date.now() + waitSec * 1000;
    while (Date.now() < deadline) {
      // 🆑 v0.9: 3с вместо 2с — меньше давления на прокси при длинных ожиданиях
      await new Promise((r) => setTimeout(r, 3000));
      const rr = await call<{ status: string; data?: unknown }>({
        label: `⏳ ожидание результата ${taskId}`,
        method: "GET",
        path: `/api/results/${taskId}`,
        silent: true,
      });
      if (rr.ok && rr.data && (rr.data as { status?: string }).status === "done") {
        set((s) => ({
          log: [
            {
              id: logId++,
              ts: Date.now(),
              label: `✅ Результат: ${opts.label}`,
              target: `result ${taskId}`,
              ok: true,
              ms: null,
              status: 200,
              result: (rr.data as { data?: unknown }).data ?? rr.data,
            },
            ...s.log,
          ].slice(0, 300),
        }));
        return { ...res, data: (rr.data as { data?: unknown }).data ?? res.data };
      }
    }
    set((s) => ({
      log: [
        {
          id: logId++,
          ts: Date.now(),
          label: `⏳ Результат не пришёл за ${waitSec}с: ${opts.label}`,
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
