#!/data/data/com.termux/files/usr/bin/sh
# ▶ ЗАПУСК ФЕРМЫ (после farm_stop.sh или с нуля)
H="${HOME:-/data/data/com.termux/files/home}"
FARM="$H/farm"

rm -f "$FARM/info/STOP"
su -c "rm -f /data/local/tmp/.farm_stop; setprop ctl.start farmkeeper" 2>/dev/null
nohup sh "$FARM/supervisor.sh" >/dev/null 2>&1 &
echo "▶ Ферма запущена (supervisor + root-страж)"
