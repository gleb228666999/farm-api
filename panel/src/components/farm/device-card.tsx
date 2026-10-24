"use client";

import { useState } from "react";
import { useFarm } from "@/lib/farm-store";
import type { FarmDevice } from "@/lib/farm-types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Separator } from "@/components/ui/separator";
import {
  Play,
  Square,
  Unlock,
  ListChecks,
  UserPlus,
  Cookie,
  Wheat,
  Radio,
  Download,
  Package,
  Terminal,
  FileText,
  Power,
  OctagonX,
  Loader2,
} from "lucide-react";
import { toast } from "sonner";

function fmtUptime(sec: number): string {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return h > 0 ? `${h}ч ${m}м` : `${m}м`;
}

function keyAgeHours(info: FarmDevice["info"]): number | null {
  const t = (info?.farm as { last_key_time?: number } | undefined)?.last_key_time;
  if (!t || t <= 0) return null;
  return (Date.now() / 1000 - t) / 3600;
}

const RESET_KEY_CMD =
  'python -c "import json,pathlib;p=pathlib.Path(\'info/farm_state.json\');d=json.loads(p.read_text()) if p.exists() else {};d[\'last_key_time\']=0;p.write_text(json.dumps(d))"';

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function DeviceCard({ device }: { device: FarmDevice }) {
  const { busy, sendTask } = useFarm();
  const id = device.device_id;

  const [harvestOpen, setHarvestOpen] = useState(false);
  const [harvestMin, setHarvestMin] = useState("20");
  const [harvestPlace, setHarvestPlace] = useState("");

  const [execOpen, setExecOpen] = useState(false);
  const [execCmd, setExecCmd] = useState("echo hello");
  const [execOut, setExecOut] = useState<string | null>(null);

  const [logOpen, setLogOpen] = useState(false);
  const [logPath, setLogPath] = useState("logs/services/farm.log");
  const [logOut, setLogOut] = useState<string | null>(null);

  const [confirmRestart, setConfirmRestart] = useState(false);
  const [confirmHalt, setConfirmHalt] = useState(false);

  const isBusy = (k: string) => !!busy[`${k}:${id}`];

  // ---------- быстрые кнопки-задачи ----------

  async function task(
    label: string,
    taskName: string,
    payload?: unknown,
    opts?: { busyKey?: string; waitSec?: number },
  ) {
    const res = await sendTask({
      label: `${label} (${id})`,
      deviceId: id,
      task: taskName,
      payload,
      busyKey: opts?.busyKey ?? `${taskName}:${id}`,
      waitSec: opts?.waitSec ?? 30,
      timeout: 20,
    });
    if (!res.ok) toast.error(`${label}: не отправлено`, { description: res.error || undefined });
    else toast.success(`${label}: отправлено ✓`);
    return res;
  }

  // ---------- БАЙПАС (принудительный) ----------

  async function forceBypass() {
    toast.info(`Байпас ${id}: шаг 1/3 — сброс кулдауна ключа`);
    // 🆑 v1.0: шаги байпаса — inline: клиент выполняет задачи ПАРАЛЛЕЛЬНО,
    // поэтому ждём завершения каждого шага, иначе фарм ▶ может обогнать фарм ⏹
    await sendTask({
      label: `Байпас 1/3: сброс кулдауна (${id})`,
      deviceId: id,
      task: "exec",
      payload: { command: RESET_KEY_CMD, timeout: 20 },
      busyKey: `bypass:${id}`,
      waitSec: 25,
      mode: "inline",
    });
    await sleep(2000);
    toast.info(`Байпас ${id}: шаг 2/3 — фарм ⏹ (закрывает роблоксы)`);
    await sendTask({
      label: `Байпас 2/3: фарм ⏹ (${id})`,
      deviceId: id,
      task: "service.stop",
      payload: { name: "farm" },
      busyKey: `bypass:${id}`,
      waitSec: 30,
      mode: "inline",
    });
    await sleep(3000);
    toast.info(`Байпас ${id}: шаг 3/3 — фарм ▶ (кулдаун 0 → байпас сразу)`);
    const res = await sendTask({
      label: `Байпас 3/3: фарм ▶ (${id})`,
      deviceId: id,
      task: "service.start",
      payload: { name: "farm" },
      busyKey: `bypass:${id}`,
      waitSec: 20,
      mode: "inline",
    });
    if (res.ok) toast.success(`Байпас ${id}: фарм перезапущен, смотри 📅 События (bypass.*)`);
  }

  // ---------- СБОР УРОЖАЯ ----------

  async function harvestStart() {
    const minutes = Math.max(1, Math.min(parseInt(harvestMin || "20", 10) || 20, 180));
    setHarvestOpen(false);
    await task(
      `Сбор 🌾 старт ${minutes}мин`,
      "harvest.start",
      { minutes, place_id: harvestPlace.trim() },
      { busyKey: "harvest", waitSec: 20 },
    );
  }

  // ---------- EXEC ----------

  async function runExec() {
    if (!execCmd.trim()) return;
    setExecOut(null);
    const res = await sendTask({
      label: `Exec на ${id}`,
      deviceId: id,
      task: "exec",
      payload: { command: execCmd, timeout: 60 },
      busyKey: "exec",
      waitSec: 45,
      timeout: 20,
      mode: "inline", // вывод нужен в диалоге
    });
    if (res.ok) {
      const d = res.data as { output?: string; ok?: boolean; error?: string } | null;
      setExecOut(
        d
          ? `ok: ${d.ok ?? "?"}\n${d.error ? "error: " + d.error + "\n" : ""}--- вывод ---\n${d.output ?? "(пусто)"}`
          : JSON.stringify(res.data, null, 2),
      );
    } else {
      setExecOut("Ошибка: " + (res.error || "неизвестно"));
    }
  }

  // ---------- ЧТЕНИЕ ФАЙЛА (логи) ----------

  async function readLog() {
    if (!logPath.trim()) return;
    setLogOut(null);
    const res = await sendTask({
      label: `Чтение ${logPath} на ${id}`,
      deviceId: id,
      task: "file.read",
      payload: { path: logPath.trim(), tail: 4000 },
      busyKey: "file",
      waitSec: 25,
      mode: "inline", // содержимое файла нужно в диалоге
    });
    if (res.ok) {
      const d = res.data as { content?: string; error?: string } | null;
      setLogOut(d?.content ?? d?.error ?? JSON.stringify(res.data, null, 2));
    } else {
      setLogOut("Ошибка: " + (res.error || "неизвестно"));
    }
  }

  const ka = keyAgeHours(device.info);

  return (
    <Card className="gap-3 py-4">
      <CardHeader className="px-4">
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle className="font-mono text-base">{id}</CardTitle>
          {device.online ? (
            <Badge className="bg-emerald-600">онлайн</Badge>
          ) : (
            <Badge variant="secondary" className="opacity-70">
              офлайн · {device.last_seen_sec}с назад
            </Badge>
          )}
          {device.client_version && (
            <Badge variant="outline">клиент v{device.client_version}</Badge>
          )}
          {device.groups.map((g) => (
            <Badge key={g} variant="outline" className="border-amber-600 text-amber-600">
              👥 {g}
            </Badge>
          ))}
        </div>
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span>
            📱 {device.info?.model || "?"} · Android {device.info?.android || "?"}
          </span>
          {device.info?.battery != null && <span>🔋 {device.info.battery}%</span>}
          <span>⏱ аптайм клиента: {fmtUptime(device.uptime_sec)}</span>
          {ka !== null && (
            <span>🔑 ключ: {ka < 24 ? `${ka.toFixed(1)}ч` : `${(ka / 24).toFixed(1)}сут`}</span>
          )}
        </div>
      </CardHeader>

      <Separator />

      <CardContent className="px-4">
        {/* --- ФАРМ --- */}
        <div className="mb-2">
          <p className="mb-1.5 text-xs font-semibold text-muted-foreground uppercase">Фарм</p>
          <div className="flex flex-wrap gap-1.5">
            <Button
              size="sm"
              variant="outline"
              disabled={!device.online || isBusy("service.start")}
              onClick={() => task("Фарм ▶", "service.start", { name: "farm" })}
            >
              {isBusy("service.start") ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              Фарм ▶
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!device.online || isBusy("service.stop")}
              onClick={() => task("Фарм ⏹", "service.stop", { name: "farm" })}
            >
              {isBusy("service.stop") ? <Loader2 className="h-4 w-4 animate-spin" /> : <Square className="h-4 w-4" />}
              Фарм ⏹
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={!device.online || isBusy("bypass")}
              onClick={forceBypass}
            >
              {isBusy("bypass") ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Unlock className="h-4 w-4" />
              )}
              Байпас (принуд.)
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!device.online || isBusy("service.status")}
              onClick={() => task("Сервисы: статус", "service.status", undefined, { waitSec: 20 })}
            >
              <ListChecks className="h-4 w-4" />
              Статус сервисов
            </Button>
          </div>
        </div>

        {/* --- РЕГА / КУКИ / СБОР --- */}
        <div className="mb-2">
          <p className="mb-1.5 text-xs font-semibold text-muted-foreground uppercase">
            Рег акков · Куки · Сбор
          </p>
          <div className="flex flex-wrap gap-1.5">
            <Button
              size="sm"
              variant="outline"
              disabled={!device.online || isBusy("rega.start")}
              onClick={() => task("Рег акков 🆕 (20 попыток)", "rega.start", { target: 5 })}
            >
              {isBusy("rega.start") ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
              Рег акков
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!device.online || isBusy("cookie.check")}
              onClick={() => task("Проверка кук 🍪", "cookie.check", {}, { waitSec: 15 })}
            >
              <Cookie className="h-4 w-4" />
              Проверка кук
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!device.online || isBusy("harvest.start")}
              onClick={() => setHarvestOpen(true)}
            >
              <Wheat className="h-4 w-4" />
              Сбор 🌾 старт…
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!device.online || isBusy("harvest.stop")}
              onClick={() => task("Сбор 🌾 стоп", "harvest.stop", {}, { waitSec: 15 })}
            >
              <Square className="h-4 w-4" />
              Сбор стоп
            </Button>
          </div>
        </div>

        {/* --- СЕРВИС / ОБСЛУЖИВАНИЕ --- */}
        <div>
          <p className="mb-1.5 text-xs font-semibold text-muted-foreground uppercase">
            Связь и обслуживание
          </p>
          <div className="flex flex-wrap gap-1.5">
            <Button
              size="sm"
              variant="outline"
              disabled={!device.online || isBusy("ping")}
              onClick={() => task("Ping", "ping", undefined, { waitSec: 15 })}
            >
              <Radio className="h-4 w-4" />
              Ping
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!device.online || isBusy("update")}
              onClick={() => task("Update клиента", "update", {}, { waitSec: 45 })}
            >
              <Download className="h-4 w-4" />
              Update
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!device.online || isBusy("apk.update")}
              onClick={() => task("APK update", "apk.update", { reboot: false }, { waitSec: 60 })}
            >
              <Package className="h-4 w-4" />
              APK
            </Button>
            <Button size="sm" variant="outline" onClick={() => setLogOpen(true)}>
              <FileText className="h-4 w-4" />
              Логи…
            </Button>
            <Button size="sm" variant="outline" onClick={() => setExecOpen(true)}>
              <Terminal className="h-4 w-4" />
              Exec…
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!device.online || isBusy("restart")}
              onClick={() => setConfirmRestart(true)}
            >
              <Power className="h-4 w-4" />
              Restart
            </Button>
            <Button
              size="sm"
              variant="destructive"
              disabled={!device.online || isBusy("halt")}
              onClick={() => setConfirmHalt(true)}
            >
              <OctagonX className="h-4 w-4" />
              Halt
            </Button>
          </div>
        </div>
      </CardContent>

      {/* Диалог: Сбор урожая */}
      <Dialog open={harvestOpen} onOpenChange={setHarvestOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>🌾 Сбор урожая на {id}</DialogTitle>
            <DialogDescription>
              Фарм зайдёт в приватки на время окна. Пустой place_id = свой PLACE_ID телефона.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor={`hv-min-${id}`}>Минуты (1–180)</Label>
              <Input
                id={`hv-min-${id}`}
                value={harvestMin}
                onChange={(e) => setHarvestMin(e.target.value)}
                inputMode="numeric"
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor={`hv-place-${id}`}>Place ID (необязательно)</Label>
              <Input
                id={`hv-place-${id}`}
                value={harvestPlace}
                onChange={(e) => setHarvestPlace(e.target.value)}
                placeholder="142823291"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setHarvestOpen(false)}>
              Отмена
            </Button>
            <Button onClick={harvestStart}>Запустить сбор</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Диалог: Exec */}
      <Dialog open={execOpen} onOpenChange={setExecOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>⌨️ Команда на {id}</DialogTitle>
            <DialogDescription>
              Shell-команда в Termux (cwd = папка клиента). До 180с.
            </DialogDescription>
          </DialogHeader>
          <Input
            value={execCmd}
            onChange={(e) => setExecCmd(e.target.value)}
            placeholder="ls -la; ps aux | grep farm"
            className="font-mono text-xs"
          />
          {execOut !== null && (
            <pre className="max-h-64 overflow-y-auto rounded-md bg-zinc-950 p-3 font-mono text-xs whitespace-pre-wrap text-emerald-300">
              {execOut}
            </pre>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setExecOpen(false)}>
              Закрыть
            </Button>
            <Button onClick={runExec} disabled={isBusy("exec")}>
              {isBusy("exec") ? <Loader2 className="h-4 w-4 animate-spin" /> : <Terminal className="h-4 w-4" />}
              Выполнить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Диалог: Логи */}
      <Dialog open={logOpen} onOpenChange={setLogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>📄 Файл на {id}</DialogTitle>
            <DialogDescription>
              Последние 4000 символов. Примеры: logs/services/farm.log, logs/services/rega.log,
              info/farm_state.json
            </DialogDescription>
          </DialogHeader>
          <div className="flex gap-2">
            <Input
              value={logPath}
              onChange={(e) => setLogPath(e.target.value)}
              className="font-mono text-xs"
            />
            <Button onClick={readLog} disabled={isBusy("file")} size="sm">
              {isBusy("file") ? <Loader2 className="h-4 w-4 animate-spin" /> : "Прочитать"}
            </Button>
          </div>
          {logOut !== null && (
            <pre className="max-h-72 overflow-y-auto rounded-md bg-zinc-950 p-3 font-mono text-xs whitespace-pre-wrap text-zinc-200">
              {logOut}
            </pre>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setLogOpen(false)}>
              Закрыть
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Подтверждение Restart */}
      <AlertDialog open={confirmRestart} onOpenChange={setConfirmRestart}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Перезапустить клиент на {id}?</AlertDialogTitle>
            <AlertDialogDescription>
              Клиент завершится, supervisor поднимет его примерно через 60с. Сервисы продолжат работать.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction
              onClick={() =>
                task("Restart клиента", "restart", undefined, { waitSec: 15, busyKey: "restart" })
              }
            >
              Перезапустить
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Подтверждение Halt */}
      <AlertDialog open={confirmHalt} onOpenChange={setConfirmHalt}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Полный стоп {id}?</AlertDialogTitle>
            <AlertDialogDescription>
              farm_stop.sh: клиент + supervisor + страж будут остановлены. Телефон отключится
              от сервера до ручного запуска.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-white"
              onClick={() =>
                task("HALT (полный стоп)", "halt", undefined, { waitSec: 15, busyKey: "halt" })
              }
            >
              Остановить всё
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  );
}
