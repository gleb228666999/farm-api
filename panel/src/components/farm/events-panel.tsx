"use client";

import { useCallback, useEffect, useState } from "react";
import { useFarm } from "@/lib/farm-store";
import type { FarmEvent } from "@/lib/farm-types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { RefreshCw, Loader2, Trash2, CalendarClock } from "lucide-react";
import { toast } from "sonner";

function fmtTs(ts: number): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleTimeString("ru-RU");
}

function typeBadge(t: string) {
  if (t.includes("fail") || t.includes("crash") || t.includes("stop"))
    return <Badge variant="destructive">{t}</Badge>;
  if (t.includes("ok") || t.includes("start") || t.includes("done"))
    return <Badge className="bg-emerald-600">{t}</Badge>;
  return <Badge variant="secondary">{t}</Badge>;
}

export function EventsPanel() {
  const base = useFarm((s) => s.base);
  if (!base) {
    return (
      <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
        Укажи адрес сервера фермы в поле сверху.
      </p>
    );
  }
  return <EventsInner key={base} />;
}

function EventsInner() {
  const { call, busy } = useFarm();
  const [events, setEvents] = useState<FarmEvent[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [fDevice, setFDevice] = useState("");
  const [fType, setFType] = useState("");
  const [limit, setLimit] = useState("100");

  const refresh = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      const res = await call<{ count: number; events: FarmEvent[] }>({
        label: "📅 События фарма",
        method: "GET",
        path: "/api/events",
        query: { device_id: fDevice.trim(), type: fType.trim(), limit: limit || "100" },
        silent,
      });
      if (!silent) setLoading(false);
      if (res.ok && res.data) setEvents(res.data.events || []);
      else if (!silent)
        toast.error("Не получил события", { description: res.error || undefined });
    },
    [fDevice, fType, limit, call],
  );

  useEffect(() => {
    const t = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(t);
  }, [refresh]);

  async function clearEvents() {
    const res = await call({
      label: "🗑 Очистить историю событий",
      method: "DELETE",
      path: "/api/events",
      busyKey: "events-clear",
    });
    if (res.ok) {
      toast.success("История событий очищена");
      void refresh(true);
    } else toast.error("Не очистилось", { description: res.error || undefined });
  }

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <CalendarClock className="h-4 w-4" />
          События фарма (SQLite) {events ? `· ${events.length}` : ""}
        </CardTitle>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            value={fDevice}
            onChange={(e) => setFDevice(e.target.value)}
            placeholder="device_id"
            className="h-8 w-32 font-mono text-xs"
            aria-label="фильтр по устройству"
          />
          <Input
            value={fType}
            onChange={(e) => setFType(e.target.value)}
            placeholder="тип (bypass.ok)"
            className="h-8 w-36 font-mono text-xs"
            aria-label="фильтр по типу события"
          />
          <Input
            value={limit}
            onChange={(e) => setLimit(e.target.value)}
            inputMode="numeric"
            className="h-8 w-16 text-xs"
            aria-label="лимит"
          />
          <Button size="sm" variant="outline" onClick={() => void refresh()} disabled={loading}>
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            Обновить
          </Button>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button size="sm" variant="destructive" disabled={busy["events-clear"]}>
                <Trash2 className="h-4 w-4" />
                Очистить
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Удалить всю историю событий?</AlertDialogTitle>
                <AlertDialogDescription>
                  Таблица events в SQLite на сервере будет полностью очищена. Отменить нельзя.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Отмена</AlertDialogCancel>
                <AlertDialogAction className="bg-destructive text-white" onClick={clearEvents}>
                  Очистить
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </CardHeader>
      <CardContent className="max-h-[32rem] overflow-y-auto">
        {events === null ? (
          <p className="py-6 text-center text-sm text-muted-foreground">загрузка…</p>
        ) : events.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            Событий нет. Они появятся, когда телефоны начнут фармить (farm.start, bypass.ok,
            harvest.* и т.д.).
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-24">Время (телефон)</TableHead>
                <TableHead className="w-32">Устройство</TableHead>
                <TableHead className="w-40">Тип</TableHead>
                <TableHead>Детали</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {events.map((e) => (
                <TableRow key={e.id}>
                  <TableCell className="font-mono text-xs">{fmtTs(e.ts)}</TableCell>
                  <TableCell className="font-mono text-xs">{e.device_id}</TableCell>
                  <TableCell>{typeBadge(e.type)}</TableCell>
                  <TableCell className="max-w-md truncate font-mono text-xs text-muted-foreground">
                    {Object.keys(e.info || {}).length ? JSON.stringify(e.info) : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
