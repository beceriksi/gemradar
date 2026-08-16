import os
import json
import time
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============== AYARLAR (istediğin gibi değiştir) ==============
MIN_24H_TURNOVER_USDT = 300_000       # Bu hacmin altındaki coinlere hiç bakma (gürültüyü azaltır)

EARLY_VOLUME_THRESHOLD_PCT = 40       # Hacim artışı bu yüzdenin üstündeyse "dikkat çekici"
MAX_PRICE_MOVE_PCT = 2.5              # Fiyat bu aralığın DIŞINA henüz çıkmamış olmalı (kırılım olmamış)
MIN_BUY_PRESSURE = 0.15               # Mum içi alım baskısı (Close Location Value), -1..+1 arası, 0 üstü alıcı baskın demek

BASELINE_HOURS = 20                   # Ortalama hacim kaç saatlik geçmişten hesaplansın
COOLDOWN_MINUTES = 90                 # Aynı coin için tekrar uyarı vermeden önce beklenecek süre
MAX_WORKERS = 8                       # Eşzamanlı istek sayısı
STATE_FILE = "state.json"

OKX_TICKERS_URL = "https://www.okx.com/api/v5/market/tickers"
OKX_CANDLES_URL = "https://www.okx.com/api/v5/market/candles"

TELEGRAM_TOKEN   = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


def get_usdt_symbols():
    """24s hacmi belirli bir eşiğin üzerinde olan USDT paritelerini getirir (OKX spot)."""
    r = requests.get(OKX_TICKERS_URL, params={"instType": "SPOT"}, timeout=15)
    r.raise_for_status()
    data = r.json()["data"]
    symbols = []
    for item in data:
        inst_id = item["instId"]          # örn: "BTC-USDT"
        if not inst_id.endswith("-USDT"):
            continue
        turnover = float(item.get("volCcy24h", 0) or 0)   # USDT cinsinden 24s hacim
        if turnover >= MIN_24H_TURNOVER_USDT:
            symbols.append(inst_id)
    return symbols


def analyze_symbol(inst_id):
    """
    Son kapanan saatlik mumu inceler:
    - hacim geçmiş ortalamaya göre ne kadar arttı
    - fiyat henüz ne kadar hareket etti (az hareket = henüz kırılmamış)
    - mum içindeki alım baskısı (kapanış mumun tepesine mi dibine mi yakın)
    """
    try:
        r = requests.get(
            OKX_CANDLES_URL,
            params={"instId": inst_id, "bar": "1H", "limit": str(BASELINE_HOURS + 3)},
            timeout=15,
        )
        r.raise_for_status()
        rows = r.json()["data"]
        # OKX formatı: [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
        # en yeniden en eskiye doğru döner -> kronolojik sıraya çeviriyoruz
        rows = sorted(rows, key=lambda x: int(x[0]))
        # confirm == "1" olan mumlar kapanmış demektir, sadece onları kullan
        closed = [row for row in rows if row[8] == "1"]
        if len(closed) < BASELINE_HOURS + 2:
            return None

        last = closed[-1]
        baseline = closed[-1 - BASELINE_HOURS:-1]

        last_open  = float(last[1])
        last_high  = float(last[2])
        last_low   = float(last[3])
        last_close = float(last[4])
        last_volume = float(last[6])   # volCcy: USDT cinsinden hacim

        baseline_vols = [float(c[6]) for c in baseline]
        if not baseline_vols:
            return None
        avg_baseline = sum(baseline_vols) / len(baseline_vols)
        if avg_baseline <= 0:
            return None

        vol_change_pct = (last_volume - avg_baseline) / avg_baseline * 100
        price_change_pct = (last_close - last_open) / last_open * 100 if last_open > 0 else 0

        candle_range = last_high - last_low
        clv = ((last_close - last_low) - (last_high - last_close)) / candle_range if candle_range > 0 else 0

        early_move = (
            vol_change_pct >= EARLY_VOLUME_THRESHOLD_PCT
            and abs(price_change_pct) <= MAX_PRICE_MOVE_PCT
            and clv >= MIN_BUY_PRESSURE
        )

        if early_move:
            return {
                "symbol": inst_id.replace("-", ""),   # TradingView'de aratmak için: BTCUSDT
                "vol_change_pct": vol_change_pct,
                "price_change_pct": price_change_pct,
                "clv": clv,
            }
    except Exception:
        return None
    return None


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        },
        timeout=15,
    )


def main():
    now = time.time()
    state = load_state()

    symbols = get_usdt_symbols()
    print(f"{len(symbols)} USDT paritesi taranıyor...")

    hits = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(analyze_symbol, s): s for s in symbols}
        for fut in as_completed(futures):
            result = fut.result()
            if result:
                hits.append(result)

    # cooldown filtresi: yakın zamanda uyarı verilmiş coini tekrar gönderme
    fresh_hits = []
    for h in hits:
        last_alert = state.get(h["symbol"])
        if last_alert and (now - last_alert) < COOLDOWN_MINUTES * 60:
            continue
        fresh_hits.append(h)
        state[h["symbol"]] = now

    if fresh_hits:
        fresh_hits.sort(key=lambda x: x["vol_change_pct"], reverse=True)
        lines = ["👀 *Sessiz Alım Tespit Edildi (henüz kırılmadı)* 👀", ""]
        for h in fresh_hits[:15]:
            lines.append(
                f"🔎 *{h['symbol']}*  Hacim: +%{h['vol_change_pct']:.0f}  "
                f"Fiyat: %{h['price_change_pct']:.2f}  Baskı: {h['clv']:.2f}"
            )
        lines.append("")
        lines.append("_TradingView'de sembolü ara: SYMBOL + USDT_")
        lines.append(f"_{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_")
        send_telegram("\n".join(lines))
        print(f"{len(fresh_hits)} coin için Telegram mesajı gönderildi.")
    else:
        print("Kritere uyan yeni bir coin bulunamadı.")

    save_state(state)


if __name__ == "__main__":
    main()
