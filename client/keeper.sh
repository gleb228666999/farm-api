#!/system/bin/sh
# 🛡 Farm Keeper — root-страж (слой 6), схема v7.2.
# Запускается из /data/adb/service.d/98farm.sh (Magisk, при загрузке).
# Полная остановка: sh /data/data/com.termux/files/home/farm/farm_stop.sh
PIDF=/data/local/tmp/.farm_keeper.pid
STOP1=/data/data/com.termux/files/home/farm/info/STOP
STOP2=/data/local/tmp/.farm_stop
HOME_T=/data/data/com.termux/files/home
TSH=/data/data/com.termux/files/usr/bin/sh
CLIENT_PIDF="$HOME_T/farm/info/client.pid"

echo $$ > "$PIDF"

client_alive() {
    pid=$(/system/bin/cat "$CLIENT_PIDF" 2>/dev/null)
    [ -z "$pid" ] && return 1
    [ -d "/proc/$pid" ] || return 1
    /system/bin/grep -q "farm/main.py" "/proc/$pid/cmdline" 2>/dev/null
}

sup_alive() {
    for d in /proc/[0-9]*; do
        [ "$d" = "/proc/$$" ] && continue
        c="$(/system/bin/tr '\0' ' ' < "$d/cmdline" 2>/dev/null)"
        case "$c" in *supervisor.sh*) return 0 ;; esac
    done
    return 1
}

while true; do
    # STOP (второй путь читается даже при зашифрованном после ребута Termux)
    stop=0
    [ -f "$STOP1" ] && stop=1
    [ -f "$STOP2" ] && stop=1
    if [ "$stop" = "1" ]; then
        /system/bin/sleep 60
        continue
    fi
    # Termux-приложение убито системой? Открываем — bashrc поднимет supervisor
    if ! /system/bin/pidof com.termux >/dev/null 2>&1; then
        /system/bin/am start --user 0 -n com.termux/.app.TermuxActivity >/dev/null 2>&1
        /system/bin/sleep 45
        continue
    fi
    if client_alive; then
        :
    elif ! sup_alive; then
        # supervisor мёртв → поднимаем напрямую (он сам сменит uid на Termux)
        /system/bin/setsid "$TSH" "$HOME_T/farm/supervisor.sh" >/dev/null 2>&1 &
    fi
    /system/bin/sleep 60
done
