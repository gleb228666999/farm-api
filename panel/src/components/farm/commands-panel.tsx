"use client";

import { useCallback, useEffect, useState } from "react";
import { useFarm } from "@/lib/farm-store";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import {
  UserPlus,
  Wheat,
  Cookie,
  Download,
  Play,
  Square,
  Radio,
  Film,
  Send,
  Loader2,
  Hourglass,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";

type BroadcastResp = {
  sent?: number;
  delivered?: string[];
  stale?: string[];
};

export function CommandsPanel() {
  const { busy, call, sendTask, health } = useFarm();
  const netDown = useFarm((s) => s.netDown);

  const [bcTask, setBcTask] = useState("ping");
  const [bcPayload, setBcPayload] = useState("{}");

  // --- онлайн-счётчик и отложенные команды (тихий опрос, как во «Функциях») ---
  const [onlineCount, setOnlineCount] = useState<number | null>(null);
  const [pendingTotal, setPendingTotal] = useState(0);

  const refresh = useCallback(async () => {
    if (useFarm.getState().netDown) return;
    if (typeof document !== "undefined" && document.hidden) return;
    const res = await call({
      label: "📱 Устройства (команды)",
      method: "GET",
      path: "/api/devices",
      silent: true,
      dedupe: true,
      timeout: 8,
    });
    if (res.ok && res.data) {
      const d = res.data as { devices?: { online: boolean }[]; pending_total?: number };
      setOnlineCount((d.devices || []).filter((x) => x.online).length);
      setPendingTotal(d.pending_total || 0);
    }
  }, [call]);

  useEffect(() => {
    const t = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(t);
  }, [refresh, health]);

  useEffect(() => {
    const iv = setInterval(() => void refresh(), 10000);
    return () => clearInterval(iv);
  }, [refresh]);

  async function serverAction(label: string, path: string, body?: unknown, busyKey?: string) {
    const res = await call({
      label,
      method: "POST",
      path,
      body: body ?? {},
      busyKey,
      timeout: 20,
    });
    const d = (res.data ?? null) as { ok?: boolean; note?: string } | null;
    if (res.ok && d?.ok !== false) {
      toast.success(`${label}: принято сервером`, {
        description: d?.note || undefined,
      });
    } else {
      toast.error(`${label}: не выполнено`, {
        description: d?.note || res.error || undefined,
      });
    }
    void refresh();
  }

  async function broadcast(label: string, task: string, payload?: unknown, busyKey?: string) {
    const res = await sendTask({
      label: `${label} → ВСЕМ`,
      deviceId: "*",
      task,
      payload,
      busyKey,
      timeout: 20,
    });
    if (!res.ok) {
      toast.error(`${label}: ошибка`, { description: res.error || undefined });
      return;
    }
    // ⏳ v0.11 честный ответ: кому реально ушла задача, а у кого связь тухлая
    const d = (res.data ?? {}) as BroadcastResp;
    const delivered = d.delivered?.length ?? d.sent ?? 0;
    const stale = d.stale?.length ?? 0;
    if (delivered === 0 && stale === 0) {
      toast.warning(`${label}: нет подключённых устройств`, {
        description: "ни один телефон сейчас не на связи с сервером",
      });
    } else if (stale > 0) {
      toast.warning(`${label}: доставлено ${delivered}, связь рвётся у ${stale}`, {
        description: `возможно не дойдёт: ${d.stale?.slice(0, 5).join(", ")}`,
      });
    } else {
      toast.success(`${label}: доставлено ${delivered}`);
    }
    void refresh();
  }

  async function clearPending() {
    const res = await call({
      label: "⏳ Снять отложенные команды",
      method: "DELETE",
      path: "/api/pending",
      busyKey: "pending-clear",
      timeout: 15,
    });
    if (res.ok) {
      toast.success("Отложенные команды сняты");
      setPendingTotal(0);
      void refresh();
    } else {
      toast.error("Не получилось", { description: res.error || undefined });
    }
  }

  async function customBroadcast() {
    let payload: unknown = {};
    try {
      payload = JSON.parse(bcPayload || "{}");
    } catch {
      toast.error("Payload — не валидный JSON");
      return;
    }
    if (!bcTask.trim()) {
      toast.error("Укажи имя задачи (например ping)");
      return;
    }
    await broadcast(`Кастом: ${bcTask}`, bcTask.trim(), payload, "custom");
  }

  const b = (k: string) => !!busy[k];
  const serverUp = health === "up";

  return (
    <div className="space-y-4">
      {/* ⏳ баннер отложенных команд + состояние */}
      {serverUp && pendingTotal > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-500/40 bg-amber-500/10 p-3">
          <div className="flex items-center gap-2 text-sm">
            <Hourglass className="h-4 w-4 text-amber-500" />
            <span>
              ⏳ Отложенных команд: <b>{pendingTotal}</b> — «Стоп фарм всем»/тумблер регы
              ждут офлайн-телефоны и применятся при их подключении (журнал: <code>/api/pending</code>)
            </span>
          </div>
          <Button size="sm" variant="outline" disabled={b("pending-clear")} onClick={clearPending}>
            {b("pending-clear") ? <Loader2 className="h-4 w-4 animate-spin" /> : <XCircle className="h-4 w-4" />}
            Снять отложенные
          </Button>
        </div>
      )}
      {serverUp && onlineCount === 0 && (
        <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
          ⚠️ Ни один телефон не на связи. Команды «для всех» некому доставить:
          «Стоп фарм всем» и тумблер регы отложатся и догонят телефоны при подключении,
          остальное (сбор/рега/обновление) потребует нажать ещё раз, когда телефоны появятся.
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Оркестрация на сервере */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">🌍 Оркестрация (сервер сам разрулит)</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-xs text-muted-foreground">
              Эти кнопки дергают планировщик сервера: он сам остановит фарм, разошлёт задачи
              всем онлайн-фармерам и соберёт урожай. {!serverUp && "Сервер не подключен — кнопки могут не сработать."}
              {serverUp && onlineCount !== null && (
                <> Онлайн устройств: <b>{onlineCount}</b>.</>
              )}
            </p>
            <div className="flex flex-wrap gap-2 pt-1">
              <Button
                variant="outline"
                disabled={b("rega-now")}
                onClick={() => serverAction("🆕 Рега сейчас", "/api/rega/start", {}, "rega-now")}
              >
                {b("rega-now") ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
                Рега сейчас
              </Button>
              <Button
                variant="outline"
                disabled={b("harvest-now")}
                onClick={() => serverAction("🌾 Сбор сейчас", "/api/harvest/start", {}, "harvest-now")}
              >
                {b("harvest-now") ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wheat className="h-4 w-4" />}
                Сбор сейчас
              </Button>
              <Button
                variant="outline"
                disabled={b("cookie-all")}
                onClick={() => serverAction("🍪 Проверка кук всем", "/api/cookie/check", {}, "cookie-all")}
              >
                {b("cookie-all") ? <Loader2 className="h-4 w-4 animate-spin" /> : <Cookie className="h-4 w-4" />}
                Проверка кук всем
              </Button>
              <Button
                variant="outline"
                disabled={b("update-all")}
                onClick={() => serverAction("⬇️ Update всем", "/api/update", { all: true }, "update-all")}
              >
                {b("update-all") ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                Update всем
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Broadcast простых задач */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">📣 Разослать задачу всем онлайн</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-xs text-muted-foreground">
              Задача уйдёт каждому подключённому устройству (websocket broadcast).
              {serverUp && onlineCount !== null && (
                <> Сейчас на связи: <b>{onlineCount}</b>.</>
              )}
            </p>
            <div className="flex flex-wrap gap-2 pt-1">
              <Button
                variant="outline"
                disabled={b("bc-farm-start")}
                onClick={() => broadcast("Фарм ▶", "service.start", { name: "farm" }, "bc-farm-start")}
              >
                {b("bc-farm-start") ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                Фарм ▶ всем
              </Button>
              <Button
                variant="outline"
                disabled={b("bc-farm-stop")}
                onClick={() => broadcast("Фарм ⏹", "service.stop", { name: "farm" }, "bc-farm-stop")}
              >
                {b("bc-farm-stop") ? <Loader2 className="h-4 w-4 animate-spin" /> : <Square className="h-4 w-4" />}
                Фарм ⏹ всем
              </Button>
              <Button
                variant="outline"
                disabled={b("bc-demo-start")}
                onClick={() => broadcast("Демо ▶", "service.start", { name: "demo" }, "bc-demo-start")}
              >
                {b("bc-demo-start") ? <Loader2 className="h-4 w-4 animate-spin" /> : <Film className="h-4 w-4" />}
                Демо-сервис ▶ всем
              </Button>
              <Button
                variant="outline"
                disabled={b("bc-demo-stop")}
                onClick={() => broadcast("Демо ⏹", "service.stop", { name: "demo" }, "bc-demo-stop")}
              >
                {b("bc-demo-stop") ? <Loader2 className="h-4 w-4 animate-spin" /> : <Square className="h-4 w-4" />}
                Демо-сервис ⏹ всем
              </Button>
              <Button
                variant="outline"
                disabled={b("bc-ping")}
                onClick={() => broadcast("Ping", "ping", undefined, "bc-ping")}
              >
                {b("bc-ping") ? <Loader2 className="h-4 w-4 animate-spin" /> : <Radio className="h-4 w-4" />}
                Ping всем
              </Button>
            </div>

            <Separator className="my-3" />

            <Label className="text-xs">Своя задача (broadcast)</Label>
            <div className="grid gap-2 sm:grid-cols-2">
              <Input
                value={bcTask}
                onChange={(e) => setBcTask(e.target.value)}
                placeholder="имя задачи, напр. exec"
                className="font-mono text-xs"
              />
              <Input
                value={bcPayload}
                onChange={(e) => setBcPayload(e.target.value)}
                placeholder='payload JSON, напр. {"command":"uptime"}'
                className="font-mono text-xs"
              />
            </div>
            <Button size="sm" variant="secondary" disabled={b("custom")} onClick={customBroadcast}>
              {b("custom") ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              Отправить всем
            </Button>
          </CardContent>
        </Card>
      </div>

      {netDown && (
        <p className="text-center text-xs text-amber-600">
          Сеть/сервер недоступны — опросы затихли. Как только связь появится, панель оживёт сама.
        </p>
      )}
    </div>
  );
}
