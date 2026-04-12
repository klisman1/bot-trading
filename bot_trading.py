"""
╔══════════════════════════════════════════════╗
║     COMPRA / VENTA V2.0 — Bot Automático     ║
║     IQ Option | 5 Activos Simultáneos       ║
╚══════════════════════════════════════════════╝
"""

from iqoptionapi.stable_api import IQ_Option
import numpy as np
import time
import json
import os
import requests
import threading
from datetime import datetime

# ─────────────────────────────────────────────
#  CONFIGURACIÓN — edita esto antes de correr
# ─────────────────────────────────────────────
EMAIL       = "klismanbaran9@gmail.com"
PASSWORD    = "klisman4088"
CUENTA      = "PRACTICE"        # "PRACTICE" o "REAL"

# ── Los 5 activos más populares en IQ Option ──
ACTIVOS = [
    "EURUSD",   # Euro / Dólar — el más operado del mundo
    "GBPUSD",   # Libra / Dólar
    "USDJPY",   # Dólar / Yen japonés
    "EURJPY",   # Euro / Yen japonés
    "AUDUSD",   # Dólar australiano / Dólar
]

TIMEFRAME   = 15    # minutos
MONTO       = 1     # dólares por operación por activo
DURACION    = 15    # minutos de expiración

# Parámetros del indicador (igual que en IQ Option)
MA_FAST   = 1
MA_SLOW   = 34
SIGNAL    = 5
VELAS_REQ = 100

# ─────────────────────────────────────────────
#  GESTIÓN DE RIESGO (global para todos los activos)
# ─────────────────────────────────────────────
STOP_PERDIDA_DIARIA = 2    # detiene TODO si pierde $2 en el día
MAX_OPERACIONES_DIA = 10   # máximo 10 operaciones por día
ESPERA_ENTRE_OPS    = 60   # segundos entre operaciones por activo

# ─────────────────────────────────────────────
#  TELEGRAM
# ─────────────────────────────────────────────
TELEGRAM_ACTIVO  = True
TELEGRAM_TOKEN   = "8545199055:AAHQWEGheocvGkBlZNSwD9pXLY6GFRbEyfg"
TELEGRAM_CHAT_ID = "8237025465"

# ─────────────────────────────────────────────
#  ARCHIVO DE LOG
# ─────────────────────────────────────────────
LOG_FILE = "operaciones.json"

# Lock para evitar conflictos entre hilos
lock = threading.Lock()

# Flag global para detener todos los hilos
bot_activo = True


# ══════════════════════════════════════════════
#  FUNCIONES DE INDICADOR
# ══════════════════════════════════════════════

def sma(values, period):
    return np.convolve(values, np.ones(period) / period, mode='valid')

def wma(values, period):
    weights = np.arange(1, period + 1, dtype=float)
    return np.convolve(values, weights / weights.sum(), mode='valid')

def get_signal(velas):
    closes = np.array([v['close'] for v in velas], dtype=float)

    if len(closes) < MA_SLOW + SIGNAL + 5:
        return False, False

    sma_fast = sma(closes, MA_FAST)
    sma_slow = sma(closes, MA_SLOW)

    min_len = min(len(sma_fast), len(sma_slow))
    b1 = sma_fast[-min_len:] - sma_slow[-min_len:]
    b2 = wma(b1, SIGNAL)

    min_len2 = min(len(b1), len(b2))
    b1 = b1[-min_len2:]
    b2 = b2[-min_len2:]

    if len(b1) < 2:
        return False, False

    buy_cross  = b1[-1] > b2[-1] and b1[-2] < b2[-2]
    sell_cross = b1[-1] < b2[-1] and b1[-2] > b2[-2]

    c = closes
    confirm_buy  = buy_cross  and c[-2] > c[-3] and c[-3] > c[-4] and c[-4] > c[-5]
    confirm_sell = sell_cross and c[-2] < c[-3] and c[-3] < c[-4] and c[-4] < c[-5]

    return confirm_buy, confirm_sell


# ══════════════════════════════════════════════
#  FUNCIONES DE LOG
# ══════════════════════════════════════════════

def cargar_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            return json.load(f)
    return {"operaciones": [], "perdida_acumulada": 0, "ganancia_acumulada": 0}

def guardar_log(data):
    with open(LOG_FILE, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def registrar_operacion(log, orden_id, activo, direccion, ganancia):
    op = {
        "id": orden_id,
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "activo": activo,
        "direccion": direccion,
        "monto": MONTO,
        "resultado": "win" if ganancia > 0 else ("loss" if ganancia < 0 else "tie"),
        "ganancia": ganancia
    }
    log["operaciones"].append(op)
    if ganancia < 0:
        log["perdida_acumulada"] += abs(ganancia)
    else:
        log["ganancia_acumulada"] += ganancia
    guardar_log(log)

def operaciones_hoy(log):
    hoy = datetime.now().strftime("%Y-%m-%d")
    return sum(1 for op in log["operaciones"] if op["fecha"].startswith(hoy))

def perdidas_hoy(log):
    hoy = datetime.now().strftime("%Y-%m-%d")
    return sum(1 for op in log["operaciones"] if op["fecha"].startswith(hoy) and op["resultado"] == "loss")


# ══════════════════════════════════════════════
#  TELEGRAM
# ══════════════════════════════════════════════

def enviar_telegram(mensaje):
    if not TELEGRAM_ACTIVO:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"}, timeout=5)
    except:
        pass


# ══════════════════════════════════════════════
#  LOOP POR ACTIVO (corre en su propio hilo)
# ══════════════════════════════════════════════

def loop_activo(iq, activo):
    global bot_activo
    print(f"  ▶ Hilo iniciado: {activo}")

    while bot_activo:
        try:
            with lock:
                log = cargar_log()
                ops_hoy    = operaciones_hoy(log)
                losses_hoy = perdidas_hoy(log)

                if losses_hoy >= 2:
                    print(f"\n🛑 [{activo}] STOP: 2 pérdidas alcanzadas hoy")
                    enviar_telegram("🛑 <b>Bot detenido</b>\n2 pérdidas alcanzadas hoy.")
                    bot_activo = False
                    return

                if log["perdida_acumulada"] >= STOP_PERDIDA_DIARIA:
                    print(f"\n🛑 [{activo}] STOP: Pérdida diaria ${STOP_PERDIDA_DIARIA} alcanzada")
                    enviar_telegram(f"🛑 <b>Bot detenido</b>\nPérdida diaria ${STOP_PERDIDA_DIARIA} alcanzada.")
                    bot_activo = False
                    return

                if ops_hoy >= MAX_OPERACIONES_DIA:
                    print(f"\n🛑 [{activo}] STOP: Máximo {MAX_OPERACIONES_DIA} operaciones alcanzado")
                    enviar_telegram(f"🛑 <b>Bot detenido</b>\n{MAX_OPERACIONES_DIA} operaciones alcanzadas.")
                    bot_activo = False
                    return

            # Obtener velas
            velas = iq.get_candles(activo, TIMEFRAME * 60, VELAS_REQ, time.time())
            if not velas:
                time.sleep(5)
                continue

            # Evaluar señal
            buy, sell = get_signal(velas)
            hora = datetime.now().strftime("%H:%M:%S")

            if buy or sell:
                direccion = "call" if buy else "put"
                emoji = "📈" if buy else "📉"
                print(f"\n[{hora}] {emoji} [{activo}] Señal {direccion.upper()}")

                status, order_id = iq.buy(MONTO, activo, direccion, DURACION)

                if not status:
                    print(f"  ❌ [{activo}] Error al ejecutar orden")
                    time.sleep(5)
                    continue

                print(f"  ✅ [{activo}] Orden abierta | ID: {order_id}")
                enviar_telegram(f"{emoji} <b>[{activo}] {direccion.upper()}</b>\nMonto: ${MONTO}\nExpiración: {DURACION} min")

                # Esperar resultado
                time.sleep(DURACION * 60 + 2)
                resultado, ganancia = iq.check_win_v3(order_id)

                emoji_r = "✅" if ganancia > 0 else ("❌" if ganancia < 0 else "➖")
                texto   = "WIN" if ganancia > 0 else ("LOSS" if ganancia < 0 else "EMPATE")
                print(f"  {emoji_r} [{activo}] {texto} | ${ganancia:.2f}")

                with lock:
                    log = cargar_log()
                    registrar_operacion(log, order_id, activo, direccion, ganancia)
                    losses_hoy = perdidas_hoy(log)

                enviar_telegram(
                    f"{emoji_r} <b>[{activo}] {texto}</b>\n"
                    f"Ganancia: ${ganancia:.2f}\n"
                    f"Pérdidas hoy: {losses_hoy}/2\n"
                    f"Ops hoy: {operaciones_hoy(log)}/{MAX_OPERACIONES_DIA}"
                )

                time.sleep(ESPERA_ENTRE_OPS)

            else:
                print(f"[{hora}] ⏳ {activo} — sin señal        ", end="\r")
                time.sleep(30)

        except Exception as e:
            print(f"  ⚠️  [{activo}] Error: {e}")
            time.sleep(5)


# ══════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════

def main():
    global bot_activo

    print("╔══════════════════════════════════════════════╗")
    print("║     COMPRA / VENTA V2.0 — Bot Automático     ║")
    print("║         5 Activos Simultáneos                ║")
    print("╚══════════════════════════════════════════════╝\n")

    print("🔌 Conectando a IQ Option...")
    iq = IQ_Option(EMAIL, PASSWORD)
    iq.connect()

    if not iq.check_connect():
        print("❌ No se pudo conectar. Verifica tu email y contraseña.")
        return

    print(f"✅ Conectado | Cuenta: {CUENTA}")
    iq.change_balance(CUENTA)

    balance = iq.get_balance()
    print(f"💰 Balance: ${balance:.2f}")
    print(f"📊 Activos: {', '.join(ACTIVOS)}")
    print(f"⏱  Timeframe: {TIMEFRAME} min | Expiración: {DURACION} min")
    print(f"🛡  Stop: 2 pérdidas o {MAX_OPERACIONES_DIA} ops máx\n")

    enviar_telegram(
        f"🤖 <b>Bot iniciado</b>\n"
        f"Cuenta: {CUENTA}\n"
        f"Balance: ${balance:.2f}\n"
        f"Activos: {', '.join(ACTIVOS)}\n"
        f"Timeframe: {TIMEFRAME} min\n"
        f"Stop: 2 pérdidas o {MAX_OPERACIONES_DIA} ops"
    )

    # Iniciar un hilo por cada activo
    hilos = []
    for activo in ACTIVOS:
        t = threading.Thread(target=loop_activo, args=(iq, activo), daemon=True)
        t.start()
        hilos.append(t)
        time.sleep(1)

    print("🤖 Bot corriendo en 5 activos... presiona Ctrl+C para detener\n")
    print("─" * 50)

    try:
        while bot_activo:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n👋 Bot detenido manualmente.")
        bot_activo = False
        enviar_telegram("👋 <b>Bot detenido</b> manualmente.")

    for t in hilos:
        t.join(timeout=5)

    # Resumen final
    log = cargar_log()
    neto = log['ganancia_acumulada'] - log['perdida_acumulada']
    print(f"\n📊 Resumen del día:")
    print(f"   Operaciones: {operaciones_hoy(log)}")
    print(f"   Pérdidas:    {perdidas_hoy(log)}")
    print(f"   Ganancia:  +${log['ganancia_acumulada']:.2f}")
    print(f"   Pérdida:   -${log['perdida_acumulada']:.2f}")
    print(f"   Neto:       ${neto:.2f}")

    enviar_telegram(
        f"📊 <b>Resumen del día</b>\n"
        f"Operaciones: {operaciones_hoy(log)}\n"
        f"Pérdidas: {perdidas_hoy(log)}\n"
        f"Ganancia: +${log['ganancia_acumulada']:.2f}\n"
        f"Pérdida: -${log['perdida_acumulada']:.2f}\n"
        f"Neto: ${neto:.2f}"
    )


if __name__ == "__main__":
    main()