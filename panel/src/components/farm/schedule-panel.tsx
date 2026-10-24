"use client";

import { useCallback, useEffect, useState } from "react";
import { useFarm } from "@/lib/farm-store";
import type { ScheduleConfig, ScheduleResponse, ScheduleState } from "@/lib/farm-types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { RefreshCw, Save, Loader2, Clock } from "lucide-react";
import { toast } from "sonner";

export function SchedulePanel() {
  const base = useFarm((s) => s.base);
  if (!base) {
    return (
      <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
        Укажи адрес сервера фермы в поле сверху.
      </p>
    );
  }
  return <ScheduleInner key={base} />;
}

function ScheduleInner() {
  const { call, busy } = useFarm();
  const [cfg, setCfg] = useState<ScheduleConfig | null>(null);
  const [state, setState] = useState<ScheduleState | null>(null);
  const [farmers, setFarmers] = useState<string[]>([]);
  const [collectors, setCollectors] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      const res = await call<ScheduleResponse>({
        label: "⏰ Расписание",
        method: "GET",
        path: "/api/schedule",
        silent,
      });
      if (!silent) setLoading(false);
      if (res.ok && res.data) {
        setCfg(res.data.schedule);
        setState(res.data.state);
        setFarmers(res.data.farmers_online || []);
        setCollectors(res.data.collectors_online || []);
      } else if (!silent) {
        toast.error("Не получил расписание", { description: res.error || undefined });
      }
    },
    [call],
  );

  useEffect(() => {
    const t = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(t);
  }, [refresh]);

  async function save() {
    if (!cfg) return;
    const res = await call({
      label: "⏰ Сохранить расписание",
      method: "POST",
      path: "/api/schedule",
      body: cfg,
      busyKey: "sched-save",
    });
    if (res.ok) {
      toast.success("Расписание сохранено");
      void refresh(true);
    } else {
      toast.error("Не сохранилось", { description: res.error || undefined });
    }
  }

  // 🛡 v0.23: тумблер «Рега акков» — kill-switch через /api/rega/switch
  // (сервер сохраняет флаг и сразу шлёт rega.switch всем онлайн-телефонам;
  // клиент пишет info/rega_switch.json и УБИВАЕТ идущую регу)
  async function toggleRega(v: boolean) {
    if (!cfg) return;
    setCfg({ ...cfg, rega_enabled: v });   // оптимистично
    const res = await call({
      label: v ? "🛡 Рега акков: включить" : "🛡 Рега акков: выключить",
      method: "POST",
      path: "/api/rega/switch",
      body: { enabled: v },
      busyKey: "rega-switch",
    });
    if (res.ok) {
      toast.success(v ? "🆕 Рега акков ВКЛЮЧЕНА" : "🛡 Рега акков ВЫКЛЮЧЕНА",
        { description: (res.data as { note?: string })?.note || undefined });
      void refresh(true);
    } else {
      setCfg({ ...cfg, rega_enabled: !v });   // откат при ошибке
      toast.error("Не переключилось", { description: res.error || undefined });
    }
  }

  const b = (k: string) => !!busy[k];

  if (!cfg) {
    return (
      <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
        {loading && <Loader2 className="h-4 w-4 animate-spin" />} загрузка…
      </div>
    );
  }

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-base">
            <Clock className="h-4 w-4" /> Конфиг (время МСК)
          </CardTitle>
          <div className="flex items-center gap-2">
            <Switch
              id="sched-enabled"
              checked={cfg.enabled}
              onCheckedChange={(v) => setCfg({ ...cfg, enabled: v })}
            />
            <Label htmlFor="sched-enabled" className="text-xs">
              включён
            </Label>
          </div>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2">
          <div className="sm:col-span-2 rounded-md border p-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <Label className="text-xs font-semibold">🛡 Рега акков (kill-switch)</Label>
                <p className="text-[11px] text-muted-foreground">
                  {cfg.rega_enabled
                    ? "ВКЛЮЧЕНА — телефоны могут регистрировать и заменять акки"
                    : "ВЫКЛЮЧЕНА (безопасный режим) — акки с лутом защищены. Кнопка «🔁 НОВЫЙ ЦИКЛ» включит её сама на время цикла"}
                </p>
              </div>
              <Switch
                id="rega-enabled"
                checked={cfg.rega_enabled}
                disabled={b("rega-switch")}
                onCheckedChange={(v) => void toggleRega(v)}
              />
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground">
              🆕 Рега запускается ТОЛЬКО кнопкой «🔁 НОВЫЙ ЦИКЛ» (Функции → Сервер — оркестрация):
              сбор завершается → рега → фарм сам встаёт с новыми акками. По расписанию рега больше
              не запускается.
            </p>
          </div>
          <div className="grid gap-1.5">
            <Label className="text-xs">🌾 Сбор урожая (ЧЧ:ММ)</Label>
            <Input
              value={cfg.harvest_time}
              onChange={(e) => setCfg({ ...cfg, harvest_time: e.target.value })}
              placeholder="20:00"
            />
          </div>
          <div className="grid gap-1.5">
            <Label className="text-xs">Проверка кук каждые (минут)</Label>
            <Input
              value={String(cfg.cookie_check_interval_min)}
              onChange={(e) =>
                setCfg({
                  ...cfg,
                  cookie_check_interval_min: parseInt(e.target.value, 10) || 30,
                })
              }
              inputMode="numeric"
            />
          </div>
          <div className="grid gap-1.5">
            <Label className="text-xs">Цель реги (акков на телефон)</Label>
            <Input
              value={String(cfg.rega_target)}
              onChange={(e) => setCfg({ ...cfg, rega_target: parseInt(e.target.value, 10) || 5 })}
              inputMode="numeric"
            />
          </div>
          <div className="grid gap-1.5">
            <Label className="text-xs">Place ID для сбора (пусто = свой)</Label>
            <Input
              value={cfg.harvest_place_id}
              onChange={(e) => setCfg({ ...cfg, harvest_place_id: e.target.value })}
              placeholder="142823291"
            />
          </div>
          <div className="sm:col-span-2">
            <Button onClick={save} disabled={b("sched-save")}>
              {b("sched-save") ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              Сохранить
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="text-base">📊 Состояние</CardTitle>
          <Button size="sm" variant="outline" onClick={() => void refresh()} disabled={loading}>
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            Обновить
          </Button>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-md border p-2">
              <p className="text-xs text-muted-foreground">Последняя рега</p>
              <p className="font-mono">{state?.last_rega || "—"}</p>
            </div>
            <div className="rounded-md border p-2">
              <p className="text-xs text-muted-foreground">Последний сбор</p>
              <p className="font-mono">{state?.last_harvest || "—"}</p>
            </div>
            <div className="rounded-md border p-2">
              <p className="text-xs text-muted-foreground">Рега в процессе (pending)</p>
              <p className="font-mono text-xs">
                {state?.rega_pending?.length ? state.rega_pending.join(", ") : "—"}
              </p>
            </div>
            <div className="rounded-md border p-2">
              <p className="text-xs text-muted-foreground">Последняя проверка кук</p>
              <p className="font-mono text-xs">
                {state?.last_check
                  ? new Date(state.last_check * 1000).toLocaleTimeString("ru-RU")
                  : "—"}
              </p>
            </div>
          </div>
          <Separator />
          <div>
            <p className="mb-1 text-xs font-semibold text-muted-foreground uppercase">
              Фармеры онлайн ({farmers.length})
            </p>
            <div className="flex flex-wrap gap-1">
              {farmers.length === 0 ? (
                <span className="text-xs text-muted-foreground">нет</span>
              ) : (
                farmers.map((f) => (
                  <Badge key={f} variant="outline" className="font-mono">
                    {f}
                  </Badge>
                ))
              )}
            </div>
          </div>
          <div>
            <p className="mb-1 text-xs font-semibold text-muted-foreground uppercase">
              Сборщики онлайн ({collectors.length})
            </p>
            <div className="flex flex-wrap gap-1">
              {collectors.length === 0 ? (
                <span className="text-xs text-muted-foreground">нет</span>
              ) : (
                collectors.map((c) => (
                  <Badge key={c} variant="outline" className="font-mono">
                    {c}
                  </Badge>
                ))
              )}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
