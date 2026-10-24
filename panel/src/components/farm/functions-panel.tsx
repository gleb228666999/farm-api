"use client";

import { useCallback, useEffect, useState } from "react";
import { useFarm } from "@/lib/farm-store";
import type { FarmDevice, FarmDevicesResponse } from "@/lib/farm-types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
  Globe,
  MonitorSmartphone,
  RefreshCw,
  RotateCcw,
} from "lucide-react";
import { toast } from "sonner";

const RESET_KEY_CMD =
  'python -c "import json,pathlib;p=pathlib.Path(\'info/farm_state.json\');d=json.loads(p.read_text()) if p.exists() else {};d[\'last_key_time\']=0;p.write_text(json.dumps(d))"';

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * 🎛 Функции — КАЖДАЯ функция отдельной кнопкой, видно СРАЗУ (без устройств тоже).
 * Цель выбирается селектором: конкретное устройство или «все» (broadcast).
 */
export function FunctionsPanel() {
  const { busy, sendTask, call, health } = useFarm();
  const netDown = useFarm((s) => s.netDown);   // 🆑 v0.9: сервер/сеть недоступны
  const [devices, setDevices] = useState<FarmDevice[] | null>(null);
  const [target, setTarget] = useState<string>("*");

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
  const [confirmCycle, setConfirmCycle] = useState(false);

  // ---- список устройств (для селектора цели) — тихо, каждые 10с ----
  // 🆑 v0.9: было 5с «без тормозов» — при медленном/недоступном сервере запросы
  // громоздились (таймаут 15с) и забивали очередь браузера → «всё лагает».
  // Теперь: 10с, дедупликация, короткий таймаут 8с, пауза в скрытой вкладке
  // и затихание опроса при недоступной сети (оживёт сам при восстановлении).
  const refresh = useCallback(async () => {
    if (useFarm.getState().netDown) return;           // сеть лежит — не спамим
    if (typeof document !== "undefined" && document.hidden) return;
    const res = await call<FarmDevicesResponse>({
      label: "📱 Список устройств",
      method: "GET",
      path: "/api/devices",
      silent: true,
      dedupe: true,
      timeout: 8,
    });
    if (res.ok && res.data) setDevices(res.data.devices || []);
  }, [call]);

  useEffect(() => {
    const t = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(t);
  }, [refresh]);

  useEffect(() => {
    const iv = setInterval(() => void refresh(), 10000);
    return () => clearInterval(iv);
  }, [refresh]);

  // 🆑 v0.9: сеть ожила (netDown → false) — сразу подтянуть список устройств
  useEffect(() => {
    if (netDown) return;
    const t = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(t);
  }, [netDown, refresh]);

  const connected = health === "up";
  const onlineDevices = (devices || []).filter((d) => d.online);
  const targetOnline =
    target === "*"
      ? onlineDevices.length > 0
      : onlineDevices.some((d) => d.device_id === target);
  const tgt = target === "*" ? "все" : target;
  const ok = connected && targetOnline;
  const isBusy = (k: string) => !!busy[`${k}:${target}`];

  // ---------- универсальная отправка задачи ----------
  async function task(
    label: string,
    taskName: string,
    payload?: unknown,
    opts?: { busyKey?: string; waitSec?: number },
  ) {
    const res = await sendTask({
      label: `${label} → ${tgt}`,
      deviceId: target,
      task: taskName,
      payload,
      busyKey: opts?.busyKey ?? `${taskName}:${target}`,
      waitSec: opts?.waitSec ?? 30,
      timeout: 20,
    });
    if (!res.ok) {
      toast.error(`${label}: не отправлено`, { description: res.error || undefined });
    } else {
      const d = res.data as { pong?: boolean; sent?: number } | null;
      toast.success(
        `${label}: ${d?.pong ? "pong ✓" : typeof d?.sent === "number" ? `отправлено ${d.sent}` : "отправлено"}`,
      );
    }
    return res;
  }

  // ---------- 🔓 БАЙПАС (принудительный): сброс кулдауна → фарм ⏹ → ▶ ----------
  async function forceBypass() {
    toast.info(`Байпас ${tgt}: шаг 1/3 — сброс кулдауна ключа`);
    await sendTask({
      label: `Байпас 1/3: сброс кулдауна → ${tgt}`,
      deviceId: target,
      task: "exec",
      payload: { command: RESET_KEY_CMD, timeout: 20 },
      busyKey: `bypass:${target}`,
      waitSec: 25,
    });
    await sleep(2000);
    toast.info(`Байпас ${tgt}: шаг 2/3 — фарм ⏹ (закрывает роблоксы)`);
    await sendTask({
      label: `Байпас 2/3: фарм ⏹ → ${tgt}`,
      deviceId: target,
      task: "service.stop",
      payload: { name: "farm" },
      busyKey: `bypass:${target}`,
      waitSec: 30,
    });
    await sleep(3000);
    toast.info(`Байпас ${tgt}: шаг 3/3 — фарм ▶ (кулдаун 0 → байпас сразу)`);
    const res = await sendTask({
      label: `Байпас 3/3: фарм ▶ → ${tgt}`,
      deviceId: target,
      task: "service.start",
      payload: { name: "farm" },
      busyKey: `bypass:${target}`,
      waitSec: 20,
    });
    if (res.ok) toast.success(`Байпас ${tgt}: запущен, смотри 📅 События (bypass.*)`);
  }

  // ---------- 🌾 СБОР ----------
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

  // ---------- 💻 EXEC / 📄 ЛОГИ ----------
  async function runExec() {
    if (!execCmd.trim()) return;
    setExecOut(null);
    const res = await sendTask({
      label: `Exec → ${tgt}`,
      deviceId: target,
      task: "exec",
      payload: { command: execCmd, timeout: 60 },
      busyKey: "exec",
      waitSec: 45,
      timeout: 20,
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

  async function readLog() {
    if (!logPath.trim()) return;
    setLogOut(null);
    const res = await sendTask({
      label: `Чтение ${logPath} → ${tgt}`,
      deviceId: target,
      task: "file.read",
      payload: { path: logPath.trim(), tail: 4000 },
      busyKey: "file",
      waitSec: 25,
    });
    if (res.ok) {
      const d = res.data as { content?: string; error?: string } | null;
      setLogOut(d?.content ?? d?.error ?? JSON.stringify(res.data, null, 2));
    } else {
      setLogOut("Ошибка: " + (res.error || "неизвестно"));
    }
  }

  // ---------- 🌐 СЕРВЕР: оркестрация (без выбора цели) ----------
  async function serverAction(path: string, label: string) {
    const res = await call({
      label,
      method: "POST",
      path,
      body: {},
      timeout: 15,
    });
    const d = res.data as { ok?: boolean; note?: string } | null;
    if (res.ok && d?.ok !== false) {
      toast.success(`${label}: запущено`, { description: d?.note || undefined });
    } else {
      toast.error(`${label}: не выполнено`, {
        description: d?.note || res.error || undefined,
      });
    }
  }

  // ---------- 🔁 НОВЫЙ ЦИКЛ: выход из HOLD-сбора → рега → фарм ----------
  // (подтверждение в AlertDialog внизу — кнопка затрагивает ВСЕ телефоны)

  const btn = (disabled: boolean) => disabled || !ok;

  return (
    <div className="space-y-4">
      {/* --- цель + состояние --- */}
      <Card className="gap-3 py-4">
        <CardHeader className="px-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <MonitorSmartphone className="h-4 w-4" />
              <span className="text-sm font-medium">Выполнять на:</span>
              <Select value={target} onValueChange={setTarget}>
                <SelectTrigger size="sm" className="w-[220px] font-mono text-xs">
                  <SelectValue placeholder="цель" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="*">🌐 все устройства (broadcast)</SelectItem>
                  {onlineDevices.map((d) => (
                    <SelectItem key={d.device_id} value={d.device_id}>
                      📱 {d.device_id} {d.info?.model ? `· ${d.info.model}` : ""}
                    </SelectItem>
                  ))}
                  {devices
                    ?.filter((d) => !d.online)
                    .map((d) => (
                      <SelectItem key={d.device_id} value={d.device_id} disabled>
                        ⚪ {d.device_id} (офлайн)
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
              {!connected && (
                <Badge variant="destructive">сервер не подключен</Badge>
              )}
              {connected && (
                <Badge className="bg-emerald-600">
                  на связи · онлайн: {onlineDevices.length}/{devices?.length ?? "?"}
                </Badge>
              )}
              {connected && !targetOnline && (
                <Badge variant="secondary">цель офлайн — выбери другую</Badge>
              )}
            </div>
            <Button size="sm" variant="outline" onClick={() => void refresh()}>
              <RefreshCw className="h-4 w-4" />
              Обновить список
            </Button>
          </div>
          {!connected && (
            <p className="mt-1 text-xs text-amber-600">
              Сервер не отвечает: проверь адрес выше и нажми «Проверить связь». Кнопки
              активируются автоматически, как только сервер ответит.
            </p>
          )}
        </CardHeader>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* --- 🚜 ФАРМ --- */}
        <Card className="gap-3 py-4">
          <CardHeader className="px-4">
            <CardTitle className="text-sm">🚜 Фарм</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-1.5 px-4">
            <Button
              size="sm"
              variant="outline"
              disabled={btn(isBusy("service.start"))}
              onClick={() => task("Фарм ▶", "service.start", { name: "farm" })}
            >
              {isBusy("service.start") ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Play className="h-4 w-4" />
              )}
              Фарм ▶
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={btn(isBusy("service.stop"))}
              onClick={() => task("Фарм ⏹", "service.stop", { name: "farm" })}
            >
              {isBusy("service.stop") ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Square className="h-4 w-4" />
              )}
              Фарм ⏹
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={btn(isBusy("bypass"))}
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
              disabled={btn(isBusy("service.status"))}
              onClick={() => task("Сервисы: статус", "service.status", undefined, { waitSec: 20 })}
            >
              <ListChecks className="h-4 w-4" />
              Статус сервисов
            </Button>
          </CardContent>
        </Card>

        {/* --- 🆕 РЕГА · 🍪 КУКИ · 🌾 СБОР --- */}
        <Card className="gap-3 py-4">
          <CardHeader className="px-4">
            <CardTitle className="text-sm">🆕 Рег акков · 🍪 Куки · 🌾 Сбор</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-1.5 px-4">
            <Button
              size="sm"
              variant="outline"
              disabled={btn(isBusy("rega.start"))}
              onClick={() => task("Рег акков 🆕 (20 попыток)", "rega.start", { target: 5 })}
            >
              {isBusy("rega.start") ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <UserPlus className="h-4 w-4" />
              )}
              Рег акков
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={btn(isBusy("cookie.check"))}
              onClick={() => task("Проверка кук 🍪", "cookie.check", {}, { waitSec: 15 })}
            >
              <Cookie className="h-4 w-4" />
              Проверка кук
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={btn(isBusy("harvest.start"))}
              onClick={() => setHarvestOpen(true)}
            >
              <Wheat className="h-4 w-4" />
              Сбор 🌾 старт…
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={btn(isBusy("harvest.stop"))}
              onClick={() => task("Сбор 🌾 стоп", "harvest.stop", {}, { waitSec: 15 })}
            >
              <Square className="h-4 w-4" />
              Сбор стоп
            </Button>
          </CardContent>
        </Card>

        {/* --- 📡 СВЯЗЬ И ОБСЛУЖИВАНИЕ --- */}
        <Card className="gap-3 py-4">
          <CardHeader className="px-4">
            <CardTitle className="text-sm">📡 Связь и обслуживание</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-1.5 px-4">
            <Button
              size="sm"
              variant="outline"
              disabled={btn(isBusy("ping"))}
              onClick={() => task("Ping", "ping", undefined, { waitSec: 15 })}
            >
              <Radio className="h-4 w-4" />
              Ping
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={btn(isBusy("update"))}
              onClick={() => task("Update клиента", "update", {}, { waitSec: 45 })}
            >
              <Download className="h-4 w-4" />
              Update
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={btn(isBusy("apk.update"))}
              onClick={() => task("APK update", "apk.update", { reboot: false }, { waitSec: 60 })}
            >
              <Package className="h-4 w-4" />
              APK
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!ok || target === "*"}
              onClick={() => setLogOpen(true)}
            >
              <FileText className="h-4 w-4" />
              Логи…
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!ok || target === "*"}
              onClick={() => setExecOpen(true)}
            >
              <Terminal className="h-4 w-4" />
              Exec…
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={btn(isBusy("restart"))}
              onClick={() => setConfirmRestart(true)}
            >
              <Power className="h-4 w-4" />
              Restart
            </Button>
            <Button
              size="sm"
              variant="destructive"
              disabled={btn(isBusy("halt"))}
              onClick={() => setConfirmHalt(true)}
            >
              <OctagonX className="h-4 w-4" />
              Halt
            </Button>
          </CardContent>
        </Card>

        {/* --- 🌐 СЕРВЕР: оркестрация --- */}
        <Card className="gap-3 py-4">
          <CardHeader className="px-4">
            <CardTitle className="flex items-center gap-1.5 text-sm">
              <Globe className="h-4 w-4" />
              Сервер — оркестрация (все фармеры сразу)
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-1.5 px-4">
            <Button
              size="sm"
              variant="outline"
              disabled={!connected}
              onClick={() => void serverAction("/api/rega/start", "🆕 Рега сейчас")}
            >
              <UserPlus className="h-4 w-4" />
              Рега сейчас
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!connected}
              onClick={() => void serverAction("/api/harvest/start", "🌾 Сбор сейчас")}
            >
              <Wheat className="h-4 w-4" />
              Сбор сейчас
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!connected}
              onClick={() => void serverAction("/api/cookie/check", "🍪 Проверка кук всем")}
            >
              <Cookie className="h-4 w-4" />
              Проверка кук всем
            </Button>
            <Button
              size="sm"
              variant="destructive"
              disabled={!connected}
              onClick={() => void serverAction("/api/farm/stop", "⏹ Стоп фарм всем")}
            >
              <Square className="h-4 w-4" />
              Стоп фарм всем
            </Button>
            <Button
              size="sm"
              variant="secondary"
              className="border border-emerald-700 bg-emerald-600/15 text-emerald-400 hover:bg-emerald-600/25"
              disabled={!connected}
              onClick={() => setConfirmCycle(true)}
            >
              <RotateCcw className="h-4 w-4" />
              НОВЫЙ ЦИКЛ
            </Button>
            <p className="w-full text-xs text-muted-foreground">
              Сбор сейчас = HOLD: фармеры зайдут в приватки с treid.lua и сидят там, пока не
              нажмёшь «НОВЫЙ ЦИКЛ» — только он завершает сбор (снимает окно → фарм ⏹ → рега акков
              → фарм сам поднимется с новыми акками). «Стоп фарм всем» = окно снято + фарм ⏹ на
              всех (без рега). Кнопки — команды серверу, селектор цели не учитывается.
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Диалог: Сбор урожая */}
      <Dialog open={harvestOpen} onOpenChange={setHarvestOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>🌾 Сбор урожая → {tgt}</DialogTitle>
            <DialogDescription>
              Окно сбора на минутах (ручной режим). Для основного потока жми «Сбор сейчас» /
              «НОВЫЙ ЦИКЛ» в блоке «Сервер — оркестрация» ниже: там сбор бессрочный (HOLD).
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="fn-hv-min">Минуты (1–180)</Label>
              <Input
                id="fn-hv-min"
                value={harvestMin}
                onChange={(e) => setHarvestMin(e.target.value)}
                inputMode="numeric"
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="fn-hv-place">Place ID (необязательно)</Label>
              <Input
                id="fn-hv-place"
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
            <DialogTitle>⌨️ Команда → {tgt}</DialogTitle>
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
              {isBusy("exec") ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Terminal className="h-4 w-4" />
              )}
              Выполнить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Диалог: Логи */}
      <Dialog open={logOpen} onOpenChange={setLogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>📄 Файл → {tgt}</DialogTitle>
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
              {isBusy("file") ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                "Прочитать"
              )}
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

      {/* Подтверждение НОВОГО ЦИКЛА */}
      <AlertDialog open={confirmCycle} onOpenChange={setConfirmCycle}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>🔁 НОВЫЙ ЦИКЛ — завершить сбор и регать акки?</AlertDialogTitle>
            <AlertDialogDescription>
              Фармеры выйдут из приваток (окно сбора снято), фарм остановится, включится рега акков
              (тумблер встанет в ВКЛ на сервере и телефонах). Когда рега закончит — фарм сам
              запустится с новыми акками. Действие для ВСЕХ фармеров сразу.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction
              className="bg-emerald-600 text-white hover:bg-emerald-700"
              onClick={() => void serverAction("/api/cycle/new", "🔁 НОВЫЙ ЦИКЛ")}
            >
              Запустить новый цикл
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Подтверждение Restart */}
      <AlertDialog open={confirmRestart} onOpenChange={setConfirmRestart}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Перезапустить клиент → {tgt}?</AlertDialogTitle>
            <AlertDialogDescription>
              Клиент завершится, supervisor поднимет его примерно через 60с. Сервисы продолжат
              работать.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction
              onClick={() =>
                task("Restart клиента", "restart", undefined, {
                  waitSec: 15,
                  busyKey: "restart",
                })
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
            <AlertDialogTitle>Полный стоп → {tgt}?</AlertDialogTitle>
            <AlertDialogDescription>
              farm_stop.sh: клиент + supervisor + страж будут остановлены. Телефон отключится от
              сервера до ручного запуска.
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
    </div>
  );
}
