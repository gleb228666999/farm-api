"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useFarm } from "@/lib/farm-store";
import type { FarmDevice, FarmDevicesResponse } from "@/lib/farm-types";
import { DeviceCard } from "@/components/farm/device-card";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { RefreshCw, Loader2, Smartphone } from "lucide-react";
import { toast } from "sonner";

export function DevicesPanel() {
  const base = useFarm((s) => s.base);
  if (!base) {
    return (
      <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
        Сначала укажи адрес сервера фермы в поле сверху и нажми «Проверить связь».
      </p>
    );
  }
  // key={base} — пересоздаёт состояние при смене сервера без сброса в эффекте
  return <DevicesInner key={base} />;
}

function DevicesInner() {
  const { call } = useFarm();
  const [devices, setDevices] = useState<FarmDevice[] | null>(null);
  const [auto, setAuto] = useState(true);
  const [loading, setLoading] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      const res = await call<FarmDevicesResponse>({
        label: "📱 Список устройств",
        method: "GET",
        path: "/api/devices",
        silent,
      });
      if (!silent) setLoading(false);
      if (res.ok && res.data) {
        setDevices(res.data.devices || []);
      } else if (!silent) {
        setDevices([]);
        toast.error("Не получил список устройств", {
          description: res.error || undefined,
        });
      }
    },
    [call],
  );

  useEffect(() => {
    const t = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(t);
  }, [refresh]);

  useEffect(() => {
    if (timer.current) clearInterval(timer.current);
    if (auto) {
      timer.current = setInterval(() => void refresh(true), 5000);
    }
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [auto, refresh]);

  const onlineCount = devices?.filter((d) => d.online).length ?? 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm">
          <Smartphone className="h-4 w-4" />
          <span className="font-medium">
            Устройств: {devices ? devices.length : "…"} · онлайн:{" "}
            {devices ? onlineCount : "…"}
          </span>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <Switch id="auto-refresh" checked={auto} onCheckedChange={setAuto} />
            <Label htmlFor="auto-refresh" className="text-xs text-muted-foreground">
              автообновление 5с
            </Label>
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={() => void refresh()}
            disabled={loading}
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            Обновить
          </Button>
        </div>
      </div>

      {devices === null && (
        <div className="space-y-3">
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      )}

      {devices !== null && devices.length === 0 && (
        <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
          Ни одного устройства не подключено. Запусти клиент на телефоне — он появится
          здесь в течение пары секунд.
        </p>
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        {devices?.map((d) => <DeviceCard key={d.device_id} device={d} />)}
      </div>
    </div>
  );
}
