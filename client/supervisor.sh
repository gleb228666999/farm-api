#!/data/data/com.termux/files/usr/bin/sh
# 🛡 Supervisor (слой 3) — схема v7.2. Клиент в foreground, рестарт через 60с.
# Стоп всего: sh ~/farm/farm_stop.sh | Запуск: sh ~/farm/farm_start.sh
BIN=/data/data/com.termux/files/usr/bin
FARM=/data/data/com.termux/files/home/farm
LOG="$FARM/logs/client.log"
SUPLOG="$FARM/logs/supervisor.log"
STOP="$FARM/info/STOP"
STOP2=/data/local/tmp/.farm_stop
PIDF="$FARM/info/client.pid"
LOCK=/data/local/tmp/.farm_supervisor.lock

# нас поднял root-страж (root)? → перезапускаемся от uid Termux,
# чтобы файлы не стали root-owned. Если su не умеет uid — продолжаем как root.
if [ "$(id -u)" = "0" ]; then
    APPUID=$(/system/bin/stat -c %u /data/data/com.termux 2>/dev/null)
    if [ -n "$APPUID" ] && [ "$APPUID" != "0" ]; then
        if su "$APPUID" -c "true" 2>/dev/null; then
            exec su "$APPUID" -c "sh $FARM/supervisor.sh"
        fi
    fi
fi

mkdir -p "$FARM/logs" "$FARM/info"

stopped() { [ -f "$STOP" ] || [ -f "$STOP2" ]; }
stopped && exit 0

sup_other() {
    for d in /proc/[0-9]*; do
        [ "$d" = "/proc/$$" ] && continue
        c="$($BIN/tr '\0' ' ' < "$d/cmdline" 2>/dev/null)"
        case "$c" in *supervisor.sh*) return 0 ;; esac
    done
    return 1
}

py_alive() {
    pid=$($BIN/cat "$PIDF" 2>/dev/null)
    [ -z "$pid" ] && return 1
    [ -d "/proc/$pid" ] || return 1
    $BIN/grep -q "farm/main.py" "/proc/$pid/cmdline" 2>/dev/null
}

if sup_other; then exit 0; fi
echo $$ > "$LOCK" 2>/dev/null
 $BIN/sleep 2
if sup_other; then exit 0; fi

log() { echo "[$($BIN/date '+%F %T')] $1" >> "$SUPLOG"; }

 $BIN/termux-wake-lock 2>/dev/null
log "👁 supervisor (pid $$): контролирую клиент"

while true; do
    stopped && { $BIN/rm -f "$LOCK" 2>/dev/null; log "STOP — выхожу"; exit 0; }
    while py_alive; do
        stopped && { $BIN/rm -f "$LOCK" 2>/dev/null; log "STOP — выхожу"; exit 0; }
        $BIN/sleep 30
    done
    stopped && exit 0
    log "⚠️ клиент мёртв → запускаю"
    "$BIN/python" "$FARM/main.py" >> "$LOG" 2>&1
    log "💀 клиент умер (exit=$?) → рестарт через 60с"
    # ротация лога клиента (как в v7.2)
    if [ -f "$LOG" ] && [ "$($BIN/wc -c < "$LOG" 2>/dev/null || echo 0)" -gt 20000000 ]; then
        $BIN/tail -n 3000 "$LOG" > "$LOG.tmp" 2>/dev/null && $BIN/mv "$LOG.tmp" "$LOG"
    fi
    $BIN/sleep 60
done
