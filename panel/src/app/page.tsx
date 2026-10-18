"use client";

import { ConnectionBar } from "@/components/farm/connection-bar";
import { FunctionsPanel } from "@/components/farm/functions-panel";
import { DevicesPanel } from "@/components/farm/devices-panel";
import { CommandsPanel } from "@/components/farm/commands-panel";
import { PoolPanel } from "@/components/farm/pool-panel";
import { EventsPanel } from "@/components/farm/events-panel";
import { GroupsPanel } from "@/components/farm/groups-panel";
import { SchedulePanel } from "@/components/farm/schedule-panel";
import { ResultsPanel } from "@/components/farm/results-panel";
import { LogPanel } from "@/components/farm/log-panel";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useFarm } from "@/lib/farm-store";
import {
  SlidersHorizontal,
  Smartphone,
  Megaphone,
  Cookie,
  CalendarClock,
  Users,
  Timer,
  Search,
  ScrollText,
} from "lucide-react";

export default function Home() {
  const { log } = useFarm();
  const errors = log.filter((l) => l.ok === false).length;

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2 px-4 py-3">
          <div>
            <h1 className="text-lg font-bold tracking-tight">
              🚜 Farm Panel — каждая функция отдельной кнопкой
            </h1>
            <p className="text-xs text-muted-foreground">
              панель управления farm-api: фарм · байпас · рега акков · сбор урожая · пул кук ·
              события · группы · расписание
            </p>
          </div>
          {errors > 0 && (
            <span className="rounded-full bg-red-500/10 px-3 py-1 text-xs font-medium text-red-500">
              ошибок в журнале: {errors}
            </span>
          )}
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl flex-1 space-y-4 px-4 py-4">
        <ConnectionBar />

        <Tabs defaultValue="functions">
          <div className="overflow-x-auto pb-1">
            <TabsList className="h-auto w-max min-w-full justify-start gap-0.5 sm:w-full">
              <TabsTrigger value="functions" className="gap-1.5">
                <SlidersHorizontal className="h-4 w-4" />
                Функции
              </TabsTrigger>
              <TabsTrigger value="devices" className="gap-1.5">
                <Smartphone className="h-4 w-4" />
                Устройства
              </TabsTrigger>
              <TabsTrigger value="commands" className="gap-1.5">
                <Megaphone className="h-4 w-4" />
                Команды
              </TabsTrigger>
              <TabsTrigger value="pool" className="gap-1.5">
                <Cookie className="h-4 w-4" />
                Пул кук
              </TabsTrigger>
              <TabsTrigger value="events" className="gap-1.5">
                <CalendarClock className="h-4 w-4" />
                События
              </TabsTrigger>
              <TabsTrigger value="groups" className="gap-1.5">
                <Users className="h-4 w-4" />
                Группы
              </TabsTrigger>
              <TabsTrigger value="schedule" className="gap-1.5">
                <Timer className="h-4 w-4" />
                Расписание
              </TabsTrigger>
              <TabsTrigger value="results" className="gap-1.5">
                <Search className="h-4 w-4" />
                Результат
              </TabsTrigger>
              <TabsTrigger value="log" className="gap-1.5">
                <ScrollText className="h-4 w-4" />
                Журнал
                {log.length > 0 && (
                  <span className="ml-1 rounded-full bg-muted px-1.5 text-xs">{log.length}</span>
                )}
              </TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="functions" className="mt-3">
            <FunctionsPanel />
          </TabsContent>
          <TabsContent value="devices" className="mt-3">
            <DevicesPanel />
          </TabsContent>
          <TabsContent value="commands" className="mt-3">
            <CommandsPanel />
          </TabsContent>
          <TabsContent value="pool" className="mt-3">
            <PoolPanel />
          </TabsContent>
          <TabsContent value="events" className="mt-3">
            <EventsPanel />
          </TabsContent>
          <TabsContent value="groups" className="mt-3">
            <GroupsPanel />
          </TabsContent>
          <TabsContent value="schedule" className="mt-3">
            <SchedulePanel />
          </TabsContent>
          <TabsContent value="results" className="mt-3">
            <ResultsPanel />
          </TabsContent>
          <TabsContent value="log" className="mt-3">
            <LogPanel />
          </TabsContent>
        </Tabs>
      </main>

      <footer className="mt-auto border-t bg-card pb-[env(safe-area-inset-bottom)]">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-1 px-4 py-2.5 text-xs text-muted-foreground">
          <span>
            🚜 Farm Panel · прокси к Farm Server v0.5 (FastAPI) · клиент v0.14 (farm / rega / demo)
          </span>
          <span>
            сервер: <code className="font-mono">main.py</code> · задачи: service.start/stop ·
            exec · rega.start · harvest.* · cookie.check · update · apk.update
          </span>
        </div>
      </footer>
    </div>
  );
}
