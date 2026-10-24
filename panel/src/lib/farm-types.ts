// Типы Farm Server API (main.py v0.5)

export type FarmDevice = {
  device_id: string;
  online: boolean;
  last_seen_sec: number;
  client_version: string | null;
  info: {
    android?: string;
    model?: string;
    battery?: number | null;
    farm?: { last_key_time?: number; [k: string]: unknown } | null;
    [k: string]: unknown;
  };
  uptime_sec: number;
  groups: string[];
  /** ⏳ v0.11: отложенные критические команды, вручаются при подключении */
  pending?: string[];
};

export type FarmDevicesResponse = {
  count: number;
  devices: FarmDevice[];
  /** ⏳ v0.11: сколько всего команд ждут офлайн-телефоны */
  pending_total?: number;
};

export type PoolEntry = {
  id: number;
  cookie: string;
  nick: string;
  pass: string;
  claimed_by: string | null;
  claimed_ts: number | null;
  added_ts: number | null;
  source: string;
};

export type PoolCounts = {
  pool: { total: number; free: number; busy: number };
  /** 🗑 v0.8: архив упразднён — сервер возвращает {total: 0} для совместимости */
  archive?: { total: number };
};

export type PoolResponse = {
  counts: PoolCounts;
  pool: PoolEntry[];
  /** 🗑 v0.8: архив упразднён — всегда [] */
  archive?: PoolEntry[];
};

export type FarmEvent = {
  id: string;
  device_id: string;
  ts: number;
  type: string;
  info: Record<string, unknown>;
  recv: number;
};

export type FarmGroup = {
  name: string;
  devices: string[];
  created: number;
};

export type ScheduleConfig = {
  enabled: boolean;
  rega_enabled: boolean;
  /** 🆕 v0.8: авторега по расписанию удалена — поле осталось только для совместимости API */
  rega_time?: string;
  harvest_time: string;
  /** 🆕 v0.8: пачки упразднены (сбор = HOLD до «НОВЫЙ ЦИКЛ») — поле для совместимости API */
  batch_minutes?: number;
  cookie_check_interval_min: number;
  rega_target: number;
  harvest_place_id: string;
};

export type ScheduleState = {
  last_rega: string;
  last_harvest: string;
  rega_pending: string[];
  rega_started: number;
  last_check: number;
};

export type ScheduleResponse = {
  schedule: ScheduleConfig;
  state: ScheduleState;
  farmers_online: string[];
  collectors_online: string[];
};

export type FarmCallResult<T = unknown> = {
  ok: boolean;
  status: number;
  ms: number;
  url?: string;
  data: T | null;
  error: string | null;
};

// ---------- типы задач клиенту (client/main.py) ----------

export type TaskName =
  | "service.start"
  | "service.stop"
  | "service.status"
  | "file.read"
  | "harvest.start"
  | "harvest.stop"
  | "rega.start"
  | "cookie.check"
  | "ping"
  | "exec"
  | "restart"
  | "halt"
  | "update"
  | "apk.update";

export const SERVICE_NAMES = ["farm", "rega", "demo"] as const;
export type ServiceName = (typeof SERVICE_NAMES)[number];
