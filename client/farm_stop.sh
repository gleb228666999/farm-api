#!/data/data/com.termux/files/usr/bin/sh
# 🛑 ПОЛНАЯ ОСТАНОВКА: клиент + сервисы + supervisor + root-страж
H="${HOME:-/data/data/com.termux/files/home}"
FARM="$H/farm"

# 1. STOP-файлы — чтобы никто не ожил посреди зачистки
touch "$FARM/info/STOP" 2>/dev/null
su -c "touch /data/local/tmp/.farm_stop" 2>/dev/null
# 2. остановить init-сервис стража (если ставился)
su -c "setprop ctl.stop farmkeeper" 2>/dev/null
sleep 1

# 3. убить всё
su -c "pkill -f 'farm/main[.]py'; pkill -f 'services/'; pkill -f 'supervisor[.]sh'; pkill -f 'keeper[.]sh'; rm -f /data/local/tmp/.farm_supervisor.lock /data/local/tmp/.farm_keeper.pid" 2>/dev/null
pkill -f 'farm/main[.]py' 2>/dev/null
pkill -f 'services/' 2>/dev/null
pkill -f 'supervisor[.]sh' 2>/dev/null
sleep 2
pkill -9 -f 'farm/main[.]py' 2>/dev/null

echo "🛑 Остановлено: клиент + supervisor + root-страж."
echo "▶ Снова запустить: sh ~/farm/farm_start.sh"
