from iqoptionapi.stable_api import IQ_Option
import numpy as np
import pandas as pd
import time
import os
import threading
import requests
from flask import Flask, render_template_string, jsonify, request

# ───────── CONFIG ─────────
EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
CUENTA = "PRACTICE"

ACTIVOS = ["EURUSD", "GBPUSD", "USDJPY"]
DURACION = 1
RIESGO = 0.02
STOP_DIARIO = 10

# 🔥 PON AQUÍ TU TOKEN NUEVO Y CHAT ID CORRECTO
TELEGRAM_ACTIVO  = True
TELEGRAM_TOKEN   = "8545199055:AAFWXG7Hh5m_KgvDTAoo_QB44pmvQZEbLLw"
TELEGRAM_CHAT_ID = "8237025465"

estado = {
    "balance": 0,
    "ganancia": 0,
    "ultima": "Esperando...",
    "historial": [],
    "equity": []
}

bot_activo = False
ganancia_total = 0

# ───────── TELEGRAM ─────────
def enviar_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg
        }, timeout=5)

        print("📩 Telegram:", r.text)

        if not r.json().get("ok"):
            print("❌ Error Telegram → revisa CHAT_ID o TOKEN")

    except Exception as e:
        print("❌ Error Telegram:", e)

# ───────── INDICADORES ─────────
def ema(data, period):
    return pd.Series(data).ewm(span=period).mean().values

def rsi(data, period=14):
    delta = np.diff(data)
    gain = np.maximum(delta, 0)
    loss = np.abs(np.minimum(delta, 0))

    avg_gain = np.mean(gain[-period:])
    avg_loss = np.mean(loss[-period:])

    if avg_loss == 0:
        return 50

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# ───────── ESTRATEGIA ─────────
def decision(iq, activo):
    velas = iq.get_candles(activo, 60, 100, time.time())
    closes = np.array([v['close'] for v in velas])

    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)
    rsi_v = rsi(closes)

    rango = max(closes[-20:]) - min(closes[-20:])
    if rango < np.mean(closes[-20:]) * 0.001:
        return None

    if ema50[-1] > ema200[-1] and rsi_v < 35:
        return "call"

    if ema50[-1] < ema200[-1] and rsi_v > 65:
        return "put"

    return None

# ───────── CONEXIÓN SEGURA ─────────
def conectar_iq():
    iq = IQ_Option(EMAIL, PASSWORD)

    while True:
        try:
            print("🔌 Conectando...")
            iq.connect()

            if iq.check_connect():
                print("✅ CONECTADO")
                enviar_telegram("🤖 Bot conectado correctamente")
                iq.change_balance(CUENTA)
                return iq

        except Exception as e:
            print("Error conexión:", e)

        time.sleep(5)

# ───────── BOT ─────────
def loop():
    global ganancia_total, bot_activo

    iq = conectar_iq()

    # 🔥 MENSAJE DE PRUEBA
    enviar_telegram("🔥 BOT INICIADO Y FUNCIONANDO")

    while True:
        if not bot_activo:
            time.sleep(1)
            continue

        try:
            if not iq.check_connect():
                print("🔄 Reconectando...")
                iq = conectar_iq()

            estado["balance"] = iq.get_balance()
            monto = estado["balance"] * RIESGO

            for activo in ACTIVOS:
                accion = decision(iq, activo)

                if accion:
                    print(f"{activo} → {accion}")

                    status, order_id = iq.buy(monto, activo, accion, DURACION)

                    if status:
                        time.sleep(DURACION * 60)
                        _, resultado = iq.check_win_v3(order_id)

                        ganancia_total += resultado

                        estado["ganancia"] = round(ganancia_total, 2)
                        estado["ultima"] = f"{activo} {accion} → {resultado:.2f}"

                        estado["historial"].append(estado["ultima"])
                        estado["equity"].append(ganancia_total)

                        enviar_telegram(estado["ultima"])

                        if ganancia_total <= -STOP_DIARIO:
                            enviar_telegram("🛑 STOP alcanzado")
                            bot_activo = False

                time.sleep(2)

        except Exception as e:
            print("⚠️ Error:", e)
            time.sleep(5)

# ───────── WEB ─────────
app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html>
<head>
<title>Trading Bot Pro</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
body {
    background: linear-gradient(to right, #0f2027, #203a43, #2c5364);
    color: white;
    text-align: center;
    font-family: Arial;
}
.card {
    background: rgba(255,255,255,0.1);
    padding: 20px;
    margin: 10px;
    border-radius: 10px;
    display: inline-block;
}
button {
    padding: 10px;
    font-size: 16px;
    margin: 5px;
}
</style>
</head>
<body>

<h1>📊 TRADING BOT PRO</h1>

<div class="card"><h3>Balance</h3><p id="balance"></p></div>
<div class="card"><h3>Ganancia</h3><p id="ganancia"></p></div>
<div class="card"><h3>Última</h3><p id="ultima"></p></div>

<br>

<button onclick="control('start')">▶️ Iniciar</button>
<button onclick="control('stop')">⛔ Detener</button>

<h2>📈 Equity</h2>
<canvas id="chart"></canvas>

<h2>📜 Historial</h2>
<ul id="historial"></ul>

<script>
let chart = new Chart(document.getElementById("chart"), {
    type: 'line',
    data: { labels: [], datasets: [{ data: [] }] }
});

async function actualizar(){
    const res = await fetch("/data");
    const d = await res.json();

    balance.innerText = d.balance;
    ganancia.innerText = d.ganancia;
    ultima.innerText = d.ultima;

    chart.data.labels = d.equity.map((_,i)=>i);
    chart.data.datasets[0].data = d.equity;
    chart.update();

    historial.innerHTML = "";
    d.historial.slice(-10).forEach(x=>{
        let li = document.createElement("li");
        li.innerText = x;
        historial.appendChild(li);
    });
}

async function control(cmd){
    await fetch("/control", {
        method:"POST",
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({cmd})
    });
}

setInterval(actualizar,2000);
</script>

</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(HTML)

@app.route("/data")
def data():
    return jsonify(estado)

@app.route("/control", methods=["POST"])
def control():
    global bot_activo

    cmd = request.json["cmd"]

    if cmd == "start":
        bot_activo = True
        enviar_telegram("▶️ Bot iniciado desde panel")

    elif cmd == "stop":
        bot_activo = False
        enviar_telegram("⛔ Bot detenido desde panel")

    return "ok"

# ───────── MAIN ─────────
def main():
    threading.Thread(target=loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)

if __name__ == "__main__":
    main()