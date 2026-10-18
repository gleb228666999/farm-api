"use client";

import { create } from "zustand";
import type { FarmCallResult } from "@/lib/farm-types";

const BASE_KEY = "farm_base_url";

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
  }) => Promise<FarmCallResult<T>>;
};

let logId = 1;

export const useFarm = create<FarmState>((set, get) => ({
  base: "",
  health: "unknown",
  healthInfo: "",
  log: [],
  busy: {},

  setBase: (v) => {
    saveBase(v);
    set({ base: v, health: "unknown", healthInfo: "" });
  },

  initBase: () => {
    const b = loadBase();
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
    const d = res.data as {
      task_id?: string;
      task_ids?: string[];
      sent?: Array<{ device_id?: string; task_id: string }>;
    } | null;
    const taskIds: string[] = [];
    if (d?.task_id) taskIds.push(d.task_id);
    if (d?.task_ids) taskIds.push(...d.task_ids);
    if (d?.sent) for (const s of d.sent) if (s?.task_id) taskIds.push(s.task_id);

    const waitSec = opts.waitSec ?? 0;
    if (!taskIds.length || waitSec <= 0 || taskIds.length > 1) return res;

    const taskId = taskIds[0];
    const deadline = Date.now() + waitSec * 1000;
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 2000));
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
    }
  },
}));
