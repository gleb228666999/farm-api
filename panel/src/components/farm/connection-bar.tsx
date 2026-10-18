"use client";

import { useEffect, useState } from "react";
import { useFarm } from "@/lib/farm-store";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Plug, PlugZap, Loader2 } from "lucide-react";
import { toast } from "sonner";

export function ConnectionBar() {
  const { base, setBase, initBase, health, healthInfo, setHealth, call } =
    useFarm();
  const [draft, setDraft] = useState("");
  const [lastBase, setLastBase] = useState("");

  useEffect(() => {
    initBase();
  }, [initBase]);

  // синхронизация draft с внешним base — паттерн «правка состояния при рендере»
  if (base !== lastBase) {
    setLastBase(base);
    setDraft(base);
  }

  async function checkHealth() {
    if (!draft.trim()) {
      toast.error("Введи адрес сервера фермы (например http://1.2.3.4:8000)");
      return;
    }
    setBase(draft.trim());
    setHealth("checking");
    const res = await call({
      label: "🔎 Проверка связи (/health)",
      method: "GET",
      path: "/health",
      timeout: 10,
    });
    if (res.ok) {
      const d = res.data as { devices?: number; time?: number } | null;
      setHealth("up", `онлайн устройств: ${d?.devices ?? "?"}`);
      toast.success("Сервер фермы отвечает", {
        description: `онлайн устройств: ${d?.devices ?? "?"}`,
      });
    } else {
      setHealth("down", res.error || "нет ответа");
      toast.error("Сервер не отвечает", {
        description: res.error || "проверь адрес и доступность",
      });
    }
  }

  return (
    <div className="flex flex-col gap-2 rounded-xl border bg-card p-3 sm:flex-row sm:items-center sm:gap-3">
      <div className="flex items-center gap-2 text-sm font-medium whitespace-nowrap">
        <Plug className="h-4 w-4 shrink-0" />
        Сервер фермы:
      </div>
      <Input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && checkHealth()}
        placeholder="http://IP-адрес:8000  (адрес твоего farm-server)"
        className="h-9 flex-1 font-mono text-xs sm:text-sm"
        aria-label="Адрес сервера фермы"
      />
      <Button onClick={checkHealth} size="sm" className="h-9 shrink-0">
        {health === "checking" ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <PlugZap className="h-4 w-4" />
        )}
        Проверить связь
      </Button>
      <div className="flex shrink-0 items-center gap-2">
        {health === "up" && <Badge className="bg-emerald-600">на связи</Badge>}
        {health === "down" && <Badge variant="destructive">не отвечает</Badge>}
        {health === "checking" && (
          <Badge variant="secondary" className="animate-pulse">
            проверяю…
          </Badge>
        )}
        {health === "unknown" && <Badge variant="outline">не проверено</Badge>}
        {healthInfo && health === "up" && (
          <span className="hidden text-xs text-muted-foreground md:inline">
            {healthInfo}
          </span>
        )}
      </div>
    </div>
  );
}
