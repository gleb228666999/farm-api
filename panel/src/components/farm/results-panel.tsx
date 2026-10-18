"use client";

import { useState } from "react";
import { useFarm } from "@/lib/farm-store";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Search, Loader2 } from "lucide-react";
import { toast } from "sonner";

export function ResultsPanel() {
  const { call, busy } = useFarm();
  const [taskId, setTaskId] = useState("");
  const [out, setOut] = useState<string | null>(null);

  async function lookup() {
    const id = taskId.trim();
    if (!id) {
      toast.error("Введи task_id (появляется в журнале после любой кнопки)");
      return;
    }
    const res = await call({
      label: `🔍 Результат задачи ${id}`,
      method: "GET",
      path: `/api/results/${encodeURIComponent(id)}`,
      busyKey: "results",
    });
    if (res.ok) {
      setOut(JSON.stringify(res.data, null, 2));
    } else {
      setOut(null);
      toast.error("Результата нет", {
        description:
          res.status === 404
            ? "такой задачи нет (TTL 1 час или телефон ещё не ответил)"
            : res.error || undefined,
      });
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">🔍 Результат задачи по task_id</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-muted-foreground">
          Каждая кнопка отправляет задачу — сервер возвращает task_id (виден в журнале).
          Результат хранится на сервере 1 час.
        </p>
        <div className="flex gap-2">
          <Input
            value={taskId}
            onChange={(e) => setTaskId(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && lookup()}
            placeholder="t_ab12cd34"
            className="w-56 font-mono text-xs"
          />
          <Button onClick={lookup} disabled={busy["results"]} size="sm">
            {busy["results"] ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            Найти
          </Button>
        </div>
        {out !== null && (
          <pre className="max-h-80 overflow-auto rounded-md bg-zinc-950 p-3 font-mono text-xs whitespace-pre-wrap text-emerald-300">
            {out}
          </pre>
        )}
      </CardContent>
    </Card>
  );
}
