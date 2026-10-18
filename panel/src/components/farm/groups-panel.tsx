"use client";

import { useCallback, useEffect, useState } from "react";
import { useFarm } from "@/lib/farm-store";
import type { FarmGroup } from "@/lib/farm-types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { RefreshCw, Plus, Trash2, Send, Loader2, Users } from "lucide-react";
import { toast } from "sonner";

const GROUP_TASKS = [
  { v: "ping", label: "ping" },
  { v: "service.start", label: "service.start" },
  { v: "service.stop", label: "service.stop" },
  { v: "harvest.start", label: "harvest.start" },
  { v: "harvest.stop", label: "harvest.stop" },
  { v: "cookie.check", label: "cookie.check" },
  { v: "rega.start", label: "rega.start" },
  { v: "update", label: "update" },
  { v: "exec", label: "exec" },
];

export function GroupsPanel() {
  const base = useFarm((s) => s.base);
  if (!base) {
    return (
      <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
        Укажи адрес сервера фермы в поле сверху.
      </p>
    );
  }
  return <GroupsInner key={base} />;
}

function GroupsInner() {
  const { call, busy } = useFarm();
  const [groups, setGroups] = useState<FarmGroup[] | null>(null);
  const [loading, setLoading] = useState(false);

  const [newName, setNewName] = useState("");
  const [newDevs, setNewDevs] = useState("");

  const [sendTaskName, setSendTaskName] = useState("ping");
  const [sendPayload, setSendPayload] = useState("{}");

  const refresh = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      const res = await call<{ groups: FarmGroup[] }>({
        label: "👥 Группы",
        method: "GET",
        path: "/api/groups",
        silent,
      });
      if (!silent) setLoading(false);
      if (res.ok && res.data) setGroups(res.data.groups || []);
      else if (!silent)
        toast.error("Не получил группы", { description: res.error || undefined });
    },
    [call],
  );

  useEffect(() => {
    const t = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(t);
  }, [refresh]);

  async function createGroup() {
    const name = newName.trim();
    if (!name) {
      toast.error("Введи имя группы");
      return;
    }
    const devices = newDevs
      .split(/[\n,;]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    const res = await call({
      label: `👥 Создать группу «${name}» (${devices.length} устр.)`,
      method: "POST",
      path: "/api/groups",
      body: { name, devices },
      busyKey: "groups-create",
    });
    if (res.ok) {
      toast.success(`Группа «${name}» сохранена (${devices.length} устр.)`);
      setNewName("");
      setNewDevs("");
      void refresh(true);
    } else toast.error("Не создалось", { description: res.error || undefined });
  }

  async function deleteGroup(name: string) {
    const res = await call({
      label: `🗑 Удалить группу «${name}»`,
      method: "DELETE",
      path: `/api/groups/${encodeURIComponent(name)}`,
      busyKey: "groups-del",
    });
    if (res.ok) {
      toast.success(`Группа «${name}» удалена`);
      void refresh(true);
    } else toast.error("Не удалилось", { description: res.error || undefined });
  }

  async function sendToGroup(name: string) {
    let payload: unknown = {};
    try {
      payload = JSON.parse(sendPayload || "{}");
    } catch {
      toast.error("Payload — не валидный JSON");
      return;
    }
    const res = await call({
      label: `📨 Задача «${sendTaskName}» → группа «${name}»`,
      method: "POST",
      path: `/api/groups/${encodeURIComponent(name)}/send`,
      body: { type: "task", task: sendTaskName, payload },
      busyKey: `groups-send-${name}`,
    });
    if (res.ok) {
      const d = res.data as { sent?: unknown[]; offline?: string[] } | null;
      toast.success(`Отправлено ${d?.sent?.length ?? 0}, офлайн: ${d?.offline?.length ?? 0}`);
    } else toast.error("Не отправилось", { description: res.error || undefined });
  }

  const b = (k: string) => !!busy[k];

  return (
    <div className="space-y-4">
      {/* Создание */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">➕ Создать / заменить группу</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="grid gap-2 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label className="text-xs">Имя группы</Label>
              <Input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="напр. baza-1"
              />
            </div>
            <div className="grid gap-1.5">
              <Label className="text-xs">
                Устройства (через запятую или с новой строки)
              </Label>
              <Textarea
                value={newDevs}
                onChange={(e) => setNewDevs(e.target.value)}
                placeholder={"0, 1, 2\ncollector-1"}
                className="max-h-24 min-h-10 overflow-y-auto font-mono text-xs"
              />
            </div>
          </div>
          <div className="flex gap-2">
            <Button onClick={createGroup} disabled={b("groups-create")}>
              {b("groups-create") ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Plus className="h-4 w-4" />
              )}
              Сохранить группу
            </Button>
            <Button variant="outline" size="sm" onClick={() => void refresh()} disabled={loading}>
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
              Обновить
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Список групп */}
      {groups !== null && groups.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Users className="h-4 w-4" /> Группы
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {groups.map((g) => (
              <div key={g.name} className="rounded-lg border p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{g.name}</span>
                    <Badge variant="secondary">{g.devices.length} устр.</Badge>
                    {g.devices.map((d) => (
                      <Badge key={d} variant="outline" className="font-mono text-xs">
                        {d}
                      </Badge>
                    ))}
                  </div>
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={() => deleteGroup(g.name)}
                    disabled={b("groups-del")}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    Удалить
                  </Button>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <Select value={sendTaskName} onValueChange={setSendTaskName}>
                    <SelectTrigger className="h-8 w-44">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {GROUP_TASKS.map((t) => (
                        <SelectItem key={t.v} value={t.v}>
                          {t.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Input
                    value={sendPayload}
                    onChange={(e) => setSendPayload(e.target.value)}
                    className="h-8 w-56 font-mono text-xs"
                    placeholder='{"name":"farm"}'
                    aria-label="payload для задачи группе"
                  />
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={b(`groups-send-${g.name}`)}
                    onClick={() => sendToGroup(g.name)}
                  >
                    {b(`groups-send-${g.name}`) ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Send className="h-4 w-4" />
                    )}
                    Отправить группе
                  </Button>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {groups !== null && groups.length === 0 && (
        <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
          Групп пока нет. Создай первую — например «baza-1» из номеров фармеров (0,1,2…)
          и «collectors» из collector-1/2/3.
        </p>
      )}
    </div>
  );
}
