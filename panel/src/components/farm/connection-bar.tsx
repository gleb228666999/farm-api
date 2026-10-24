"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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

  // 🆑 v0.9: тихая проверка — без записи в журнал и без тостов
  // (используется автовосстановлением, чтобы не засорять панель)
  const silentCheck = useCallback(
    async (url: string): Promise<boolean> => {
      const res = await call({
        label: "🔎 Проверка связи (/health)",
        method: "GET",
        path: "/health",
        timeout: 6,
        silent: true,
        dedupe: true,
      });
      if (res.ok) {
        const d = res.data as { devices?: number; time?: number } | null;
        setHealth("up", `онлайн устройств: ${d?.devices ?? "?"}`);
        return true;
      }
      setHealth("down", res.error || "нет ответа");
      return false;
    },
    [call, setHealth],
  );

  async function runCheck(url: string) {
    setHealth("checking");
    const up = await silentCheck(url);
    if (up) {
      const { healthInfo } = useFarm.getState();
      toast.success("Сервер фермы отвечает", { description: healthInfo });
    } else {
      const { healthInfo } = useFarm.getState();
      toast.error(`Сервер не отвечает (${url})`, {
        description: healthInfo || "проверь адрес и доступность",
      });
    }
  }

  async function checkHealth() {
    if (!draft.trim()) {
      toast.error("Введи адрес сервера фермы (например http://1.2.3.4:8000)");
      return;
    }
    setBase(draft.trim());
    await runCheck(draft.trim());
  }

  // --- автопроверка при загрузке: как только base известен и ещё не проверен ---
  const autoChecked = useRef("");
  useEffect(() => {
    if (!base || health !== "unknown") return;
    if (autoChecked.current === base) return;
    autoChecked.current = base;
    const t = setTimeout(() => void runCheck(base), 300);
    return () => clearTimeout(t);
  }, [base, health]);

  // --- 🆑 v0.9 АВТОВОССТАНОВЛЕНИЕ: раньше автопроверка была ОДИН раз ---
  // при загрузке. Если сервер в тот момент не ответил (перезапуск, сеть,
  // холодный старт) — панель навсегда оставалась «не отвечает», ВСЕ кнопки
  // были заблокированы («нихуя не работает»). Теперь пока health=down —
  // тихо перепроверяем каждые 12с; сервер ожил → панель сама загорится.
  useEffect(() => {
    if (health !== "down" || !base) return;
    const iv = setInterval(() => void silentCheck(base), 12000);
    return () => clearInterval(iv);
  }, [health, base, silentCheck]);

  // --- 🆑 v0.9: возврат на вкладку → сразу тихая проверка (телефон в кармане
  // часто теряет сеть; вернулся — панель должна сразу показать состояние) ---
  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState !== "visible" || !base) return;
      if (useFarm.getState().health === "checking") return;
      void silentCheck(base);
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [base, silentCheck]);

  // --- 🆑 v0.9: сообщение «сервер снова на связи» при переходе down → up ---
  const prevHealth = useRef(health);
  useEffect(() => {
    if (prevHealth.current === "down" && health === "up") {
      toast.success("Сервер снова на связи — панель разблокирована");
    }
    prevHealth.current = health;
  }, [health]);

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
        {health === "down" && (
          <span className="hidden text-xs text-muted-foreground md:inline">
            перепроверяю автоматически…
          </span>
        )}
      </div>
    </div>
  );
}
