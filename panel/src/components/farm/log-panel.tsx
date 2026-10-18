"use client";

import { useState } from "react";
import { useFarm } from "@/lib/farm-store";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ChevronDown, ChevronRight, ScrollText, Trash2 } from "lucide-react";

export function LogPanel() {
  const { log, clearLog } = useFarm();
  const [open, setOpen] = useState<Set<number>>(new Set());

  function toggle(id: number) {
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle className="flex items-center gap-2 text-base">
          <ScrollText className="h-4 w-4" />
          Журнал действий {log.length > 0 && <Badge variant="secondary">{log.length}</Badge>}
        </CardTitle>
        <Button size="sm" variant="outline" onClick={clearLog} disabled={!log.length}>
          <Trash2 className="h-4 w-4" />
          Очистить
        </Button>
      </CardHeader>
      <CardContent className="max-h-[34rem] space-y-1.5 overflow-y-auto">
        {log.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            Пусто. Нажми любую кнопку — здесь появится каждое действие и ответ сервера.
          </p>
        ) : (
          log.map((e) => (
            <div key={e.id} className="rounded-md border text-sm">
              <button
                className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-muted/40"
                onClick={() => toggle(e.id)}
                aria-expanded={open.has(e.id)}
              >
                {open.has(e.id) ? (
                  <ChevronDown className="h-3.5 w-3.5 shrink-0" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5 shrink-0" />
                )}
                <span className="shrink-0 font-mono text-xs text-muted-foreground">
                  {new Date(e.ts).toLocaleTimeString("ru-RU")}
                </span>
                <span className="min-w-0 flex-1 truncate">{e.label}</span>
                {e.ok === null && <Badge variant="outline">…</Badge>}
                {e.ok === true && <Badge className="bg-emerald-600">ok</Badge>}
                {e.ok === false && <Badge variant="destructive">ошибка</Badge>}
                {e.ms !== null && (
                  <span className="hidden shrink-0 font-mono text-xs text-muted-foreground sm:inline">
                    {e.ms}мс
                  </span>
                )}
              </button>
              {open.has(e.id) && (
                <div className="border-t px-3 py-2">
                  <p className="mb-1 font-mono text-xs text-muted-foreground">
                    {e.target}
                    {e.status ? ` → HTTP ${e.status}` : ""}
                  </p>
                  {e.error && <p className="mb-1 text-xs text-red-500">{e.error}</p>}
                  <pre className="max-h-48 overflow-auto rounded bg-zinc-950 p-2 font-mono text-xs whitespace-pre-wrap text-zinc-200">
                    {e.result === null
                      ? "(нет ответа)"
                      : typeof e.result === "string"
                        ? e.result
                        : JSON.stringify(e.result, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}
