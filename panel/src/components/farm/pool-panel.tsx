"use client";

import { useCallback, useEffect, useState } from "react";
import { useFarm } from "@/lib/farm-store";
import type { PoolEntry, PoolResponse } from "@/lib/farm-types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { RefreshCw, Plus, Trash2, ArrowRightLeft, Loader2, FlaskConical } from "lucide-react";
import { toast } from "sonner";

function short(c: string, n = 22) {
  return c.length > n ? c.slice(0, n) + "…" : c;
}

export function PoolPanel() {
  const base = useFarm((s) => s.base);
  if (!base) {
    return (
      <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
        Укажи адрес сервера фермы в поле сверху.
      </p>
    );
  }
  return <PoolInner key={base} />;
}

function PoolInner() {
  const { call, busy } = useFarm();
  const [data, setData] = useState<PoolResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [addText, setAddText] = useState("");
  const [addTo, setAddTo] = useState<"pool" | "archive">("pool");
  const [selPool, setSelPool] = useState<Set<number>>(new Set());
  const [selArch, setSelArch] = useState<Set<number>>(new Set());
  const [testDevice, setTestDevice] = useState("0");
  const [testN, setTestN] = useState("1");

  const refresh = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      const res = await call<PoolResponse>({
        label: "🍪 Пул кук",
        method: "GET",
        path: "/api/pool",
        silent,
      });
      if (!silent) setLoading(false);
      if (res.ok && res.data) {
        setData(res.data);
        setSelPool(new Set());
        setSelArch(new Set());
      } else if (!silent) {
        toast.error("Не получил пул", { description: res.error || undefined });
      }
    },
    [call],
  );

  useEffect(() => {
    const t = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(t);
  }, [refresh]);

  async function addCookies() {
    if (!addText.trim()) {
      toast.error("Вставь куки в текстовое поле");
      return;
    }
    const res = await call({
      label: `🍪 Добавить куки → ${addTo}`,
      method: "POST",
      path: "/api/pool/add",
      body: { text: addText, to: addTo, source: "panel" },
      busyKey: "pool-add",
    });
    if (res.ok) {
      const d = res.data as { added?: number } | null;
      toast.success(`Добавлено кук: ${d?.added ?? 0}`);
      setAddText("");
      void refresh(true);
    } else {
      toast.error("Добавление не сработало", { description: res.error || undefined });
    }
  }

  async function del(ids: number[], scope: string) {
    if (!ids.length) return;
    const res = await call({
      label: `🗑 Удалить кук (${scope}): ${ids.length} шт`,
      method: "POST",
      path: "/api/pool/delete",
      body: { ids },
      busyKey: "pool-del",
    });
    if (res.ok) {
      toast.success(`Удалено: ${(res.data as { deleted?: number })?.deleted ?? ids.length}`);
      void refresh(true);
    } else toast.error("Удаление не сработало", { description: res.error || undefined });
  }

  async function move(ids: number[], to: "pool" | "archive") {
    if (!ids.length) return;
    const res = await call({
      label: `↔️ Перенести ${ids.length} кук → ${to}`,
      method: "POST",
      path: "/api/pool/move",
      body: { ids, to },
      busyKey: "pool-move",
    });
    if (res.ok) {
      toast.success(`Перенесено: ${(res.data as { moved?: number })?.moved ?? ids.length}`);
      void refresh(true);
    } else toast.error("Перенос не сработал", { description: res.error || undefined });
  }

  async function testClaim() {
    const n = Math.max(1, parseInt(testN || "1", 10) || 1);
    const res = await call({
      label: `🧪 Claim ${n} кук для ${testDevice}`,
      method: "POST",
      path: "/api/pool/claim",
      body: { device_id: testDevice, n, from: "pool" },
      busyKey: "pool-claim",
    });
    if (res.ok) {
      const got = (res.data as { got?: unknown[] })?.got ?? [];
      toast.success(`Claim: получено ${got.length} из ${n} (бронь 45 мин)`);
      void refresh(true);
    } else toast.error("Claim не сработал", { description: res.error || undefined });
  }

  async function testRelease() {
    const res = await call({
      label: `🧪 Report (release) для ${testDevice}`,
      method: "POST",
      path: "/api/pool/report",
      body: { device_id: testDevice, released: [], used: [], dead: [] },
      busyKey: "pool-report",
    });
    if (res.ok) toast.success("Report отправлен (списки пустые — ничего не изменит)");
    else toast.error("Report не сработал", { description: res.error || undefined });
  }

  const b = (k: string) => !!busy[k];
  const counts = data?.counts;

  return (
    <div className="space-y-4">
      {/* Счётчики */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Card className="py-3">
          <CardHeader className="px-3 pb-0">
            <CardTitle className="text-xs font-medium text-muted-foreground">🍪 В пуле</CardTitle>
          </CardHeader>
          <CardContent className="px-3">
            <p className="text-2xl font-bold">{counts?.pool.total ?? "—"}</p>
          </CardContent>
        </Card>
        <Card className="py-3">
          <CardHeader className="px-3 pb-0">
            <CardTitle className="text-xs font-medium text-muted-foreground">✅ Свободно</CardTitle>
          </CardHeader>
          <CardContent className="px-3">
            <p className="text-2xl font-bold text-emerald-600">{counts?.pool.free ?? "—"}</p>
          </CardContent>
        </Card>
        <Card className="py-3">
          <CardHeader className="px-3 pb-0">
            <CardTitle className="text-xs font-medium text-muted-foreground">🔒 В брони</CardTitle>
          </CardHeader>
          <CardContent className="px-3">
            <p className="text-2xl font-bold text-amber-600">{counts?.pool.busy ?? "—"}</p>
          </CardContent>
        </Card>
        <Card className="py-3">
          <CardHeader className="px-3 pb-0">
            <CardTitle className="text-xs font-medium text-muted-foreground">🗄 Архив</CardTitle>
          </CardHeader>
          <CardContent className="px-3">
            <p className="text-2xl font-bold">{counts?.archive.total ?? "—"}</p>
          </CardContent>
        </Card>
      </div>

      {/* Добавление */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">➕ Добавить куки</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <Textarea
            value={addText}
            onChange={(e) => setAddText(e.target.value)}
            placeholder={
              "nick:user1\npass:pass1\n.ROBLOSECURITY=_|WARNING:-DO-NOT-SHARE-THIS...\n\nили построчно: ник:/пароль:/.ROBLOSECURITY=... или голые токены"
            }
            className="max-h-40 min-h-20 overflow-y-auto font-mono text-xs"
          />
          <div className="flex flex-wrap items-center gap-2">
            <Select value={addTo} onValueChange={(v) => setAddTo(v as "pool" | "archive")}>
              <SelectTrigger className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="pool">→ пул</SelectItem>
                <SelectItem value="archive">→ архив</SelectItem>
              </SelectContent>
            </Select>
            <Button onClick={addCookies} disabled={b("pool-add")}>
              {b("pool-add") ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Plus className="h-4 w-4" />
              )}
              Добавить
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

      {/* Списки */}
      <div className="grid gap-4 lg:grid-cols-2">
        {(
          [
            ["Пул (свободные/бронь)", data?.pool ?? [], selPool, setSelPool, "archive"],
            ["Архив (отработанные)", data?.archive ?? [], selArch, setSelArch, "pool"],
          ] as const
        ).map(([title, list, sel, setSel, moveTo]) => (
          <Card key={title}>
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle className="text-base">
                {title} <Badge variant="secondary">{list.length}</Badge>
              </CardTitle>
              <div className="flex gap-1.5">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!sel.size || b("pool-move")}
                  onClick={() => void move([...sel], moveTo)}
                >
                  <ArrowRightLeft className="h-3.5 w-3.5" />
                  → {moveTo === "pool" ? "в пул" : "в архив"}
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={!sel.size || b("pool-del")}
                  onClick={() => void del([...sel], title)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </CardHeader>
            <CardContent className="max-h-72 overflow-y-auto">
              {list.length === 0 ? (
                <p className="py-4 text-center text-xs text-muted-foreground">пусто</p>
              ) : (
                <div className="space-y-1.5">
                  {list.map((e: PoolEntry) => (
                    <div
                      key={e.id}
                      className="flex items-center gap-2 rounded-md border px-2 py-1.5 text-xs"
                    >
                      <Checkbox
                        checked={sel.has(e.id)}
                        onCheckedChange={(v) =>
                          setSel((s) => {
                            const n = new Set(s);
                            if (v) n.add(e.id);
                            else n.delete(e.id);
                            return n;
                          })
                        }
                        aria-label={`выбрать куку ${e.id}`}
                      />
                      <span className="font-mono">#{e.id}</span>
                      {e.nick && <span className="font-medium">{e.nick}</span>}
                      <span className="flex-1 truncate font-mono text-muted-foreground">
                        {short(e.cookie)}
                      </span>
                      {e.claimed_by && (
                        <Badge variant="outline" className="border-amber-600 text-amber-600">
                          🔒 {e.claimed_by}
                        </Badge>
                      )}
                      {e.source && <Badge variant="secondary">{e.source}</Badge>}
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Тестовые API телефона */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            🧪 Тест API брони (как это делает телефон)
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end gap-2">
          <div className="grid gap-1">
            <Label className="text-xs">device_id</Label>
            <Input
              value={testDevice}
              onChange={(e) => setTestDevice(e.target.value)}
              className="w-36 font-mono text-xs"
            />
          </div>
          <div className="grid gap-1">
            <Label className="text-xs">сколько кук</Label>
            <Input
              value={testN}
              onChange={(e) => setTestN(e.target.value)}
              inputMode="numeric"
              className="w-20 font-mono text-xs"
            />
          </div>
          <Button variant="outline" disabled={b("pool-claim")} onClick={testClaim}>
            {b("pool-claim") ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <FlaskConical className="h-4 w-4" />
            )}
            Забаронить (claim)
          </Button>
          <Button variant="outline" disabled={b("pool-report")} onClick={testRelease}>
            Report (release)
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
