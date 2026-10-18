"use client";

import { useState } from "react";
import { useFarm } from "@/lib/farm-store";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
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
} from "lucide-react";
import { toast } from "sonner";

export function CommandsPanel() {
  const { busy, call, sendTask } = useFarm();

  const [bcTask, setBcTask] = useState("ping");
  const [bcPayload, setBcPayload] = useState("{}");

  async function serverAction(label: string, path: string, body?: unknown, busyKey?: string) {
    const res = await call({
      label,
      method: "POST",
      path,
      body: body ?? {},
      busyKey,
      timeout: 20,
    });
    if (res.ok) {
      toast.success(`${label}: сервер принял`, {
        description: JSON.stringify(res.data)?.slice(0, 160),
      });
    } else {
      toast.error(`${label}: ошибка`, { description: res.error || undefined });
    }
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
    if (res.ok) toast.success(`${label}: разослано всем онлайн`);
    else toast.error(`${label}: ошибка`, { description: res.error || undefined });
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

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {/* Оркестрация на сервере */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">🌍 Оркестрация (сервер сам разрулит)</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <p className="text-xs text-muted-foreground">
            Эти кнопки дергают планировщик сервера: он сам остановит фарм, разошлёт задачи
            всем онлайн-фармерам и соберёт урожай пачками.
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
  );
}
