"""Демо-сервис: тик каждые 5 секунд → logs/services/demo.log"""
import time
from datetime import datetime

print("🎬 demo запущен", flush=True)
i = 0
try:
    while True:
        i += 1
        print(f"[{datetime.now():%H:%M:%S}] тик #{i}", flush=True)
        time.sleep(5)
except KeyboardInterrupt:
    print("🛑 demo остановлен", flush=True)
