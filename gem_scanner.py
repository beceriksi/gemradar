#!/usr/bin/env python3
"""
ETH Gem Radar
-------------
Ethereum'da yeni acilan, dusuk piyasa degerli ama guvenlik/likidite/sosyal
sinyalleri saglam olan token'lari tarar, skorlar ve esigi gecenleri
Telegram'a bildirim olarak yollar.

Kaynaklar:
  - GeckoTerminal API  -> yeni pool kesfi (ucretsiz, key yok)
  - GoPlus Security API -> kontrat guvenligi (ucretsiz, key yok)
  - X API v2            -> sosyal hacim/etkilesim (bearer token gerekli)
  - Telegram Bot API    -> sinyal gonderimi

Bu script bir yatirim tavsiyesi motoru DEGILDIR. Ciktisi sadece bir on-tarama
sinyalidir; nihai karar ve risk kullaniciya aittir. Dusuk piyasa degerli
token'larda rug-pull / manipulasyon riski cok yuksektir.
"""

import os
import sys
import json
import time
import requests
from datetime import datetime, timezone

# --------------------------------------------------------------------------
# AYARLAR (env degiskenleri ile override edilebilir -> GitHub Secrets)
# --------------------------------------------------------------------------

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
X_BEARER_TOKEN = os.environ.get("X_BEARER_TOKEN", "")

# Filtre esikleri (istegine gore ayarlanabilir)
MIN_MARKET_CAP_USD = float(os.environ.get("MIN_MARKET_CAP_USD", 10_000))
MAX_MARKET_CAP_USD = float(os.environ.get("MAX_MARKET_CAP_USD", 500_000))
MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 5_000))
MAX_POOL_AGE_HOURS = float(os.environ.get("MAX_POOL_AGE_HOURS", 24))
MIN_SCORE_TO_ALERT = float(os.environ.get("MIN_SCORE_TO_ALERT", 70))

STATE_FILE = "sent_tokens.json"
GECKOTERMINAL_NEW_POOLS = "https://api.geckoterminal.com/api/v2/networks/eth/new_pools"
GOPLUS_TOKEN_SECURITY = "https://api.gopluslabs.io/api/v1/token_security/1"
X_RECENT_COUNTS = "https://api.twitter.com/2/tweets/counts/recent"


# --------------------------------------------------------------------------
# STATE (daha once gonderilen adresleri tekrar atmamak icin)
# --------------------------------------------------------------------------

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {"sent": []}
    return {"sent": []}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# --------------------------------------------------------------------------
# 1) YENI POOL KESFI
# --------------------------------------------------------------------------

def fetch_new_pools():
    """GeckoTerminal'den Ethereum'daki en yeni pool'lari ceker."""
    pools = []
    try:
        resp = requests.get(
            GECKOTERMINAL_NEW_POOLS,
            params={"page": 1},
            headers={"Accept": "application/json"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        pools = data.get("data", [])
    except Exception as e:
        print(f"[HATA] GeckoTerminal cekilemedi: {e}")
    return pools


def parse_pool(pool):
    """GeckoTerminal pool objesini kullanisli bir dict'e cevirir."""
    attrs = pool.get("attributes", {})
    rels = pool.get("relationships", {})

    base_token_id = (
        rels.get("base_token", {}).get("data", {}).get("id", "")
    )  # ornek: eth_0xabc...
    contract_address = base_token_id.split("_")[-1] if "_" in base_token_id else ""

    try:
        created_at = datetime.fromisoformat(
            attrs.get("pool_created_at", "").replace("Z", "+00:00")
        )
        age_hours = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600
    except Exception:
        age_hours = 999999

    def to_float(val, default=0.0):
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    return {
        "pool_id": pool.get("id", ""),
        "name": attrs.get("name", "?"),
        "contract_address": contract_address,
        "market_cap_usd": to_float(attrs.get("market_cap_usd") or attrs.get("fdv_usd")),
        "liquidity_usd": to_float(attrs.get("reserve_in_usd")),
        "volume_24h_usd": to_float(
            (attrs.get("volume_usd") or {}).get("h24")
        ),
        "price_change_1h": to_float((attrs.get("price_change_percentage") or {}).get("h1")),
        "age_hours": age_hours,
        "dexscreener_url": f"https://dexscreener.com/ethereum/{pool.get('id', '').split('_')[-1]}",
        "geckoterminal_url": f"https://www.geckoterminal.com/eth/pools/{pool.get('id', '').split('_')[-1]}",
    }


# --------------------------------------------------------------------------
# 2) KONTRAT GUVENLIGI (GoPlus)
# --------------------------------------------------------------------------

def fetch_security(contract_address):
    """GoPlus token_security endpoint'inden guvenlik verisi ceker."""
    if not contract_address:
        return {}
    try:
        resp = requests.get(
            GOPLUS_TOKEN_SECURITY,
            params={"contract_addresses": contract_address},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        result = data.get("result", {})
        return result.get(contract_address.lower(), {})
    except Exception as e:
        print(f"[HATA] GoPlus cekilemedi ({contract_address}): {e}")
        return {}


def evaluate_security(sec):
    """
    GoPlus verisinden 0-40 puanlik guvenlik skoru + kirmizi bayrak listesi uretir.
    """
    if not sec:
        return 0, ["guvenlik verisi alinamadi"]

    flags = []
    score = 40  # tam puandan basla, sorun buldukca dus

    def is_true(key):
        return str(sec.get(key, "0")) == "1"

    if is_true("is_honeypot"):
        score -= 40
        flags.append("HONEYPOT")
    if is_true("cannot_sell_all"):
        score -= 15
        flags.append("satis kisitlamasi")
    if is_true("is_mintable"):
        score -= 10
        flags.append("mint edilebilir arz")
    if is_true("hidden_owner"):
        score -= 10
        flags.append("gizli owner")
    if is_true("can_take_back_ownership"):
        score -= 10
        flags.append("ownership geri alinabilir")
    if not is_true("is_open_source"):
        score -= 10
        flags.append("kontrat kapali kaynak")

    try:
        buy_tax = float(sec.get("buy_tax", 0) or 0)
        sell_tax = float(sec.get("sell_tax", 0) or 0)
        if buy_tax > 0.10 or sell_tax > 0.10:
            score -= 10
            flags.append(f"yuksek vergi (al:%{buy_tax*100:.0f} sat:%{sell_tax*100:.0f})")
    except Exception:
        pass

    try:
        owner_pct = float(sec.get("owner_percent", 0) or 0)
        if owner_pct > 0.05:
            score -= 10
            flags.append(f"owner arzin %{owner_pct*100:.0f}'ini tutuyor")
    except Exception:
        pass

    try:
        creator_pct = float(sec.get("creator_percent", 0) or 0)
        if creator_pct > 0.10:
            score -= 5
            flags.append(f"creator arzin %{creator_pct*100:.0f}'ini tutuyor")
    except Exception:
        pass

    if is_true("is_anti_whale") is False and is_true("is_whitelisted"):
        flags.append("whitelist mekanizmasi var (dikkat)")

    score = max(0, min(40, score))
    return score, flags


# --------------------------------------------------------------------------
# 3) SOSYAL SINYAL (X / Twitter)
# --------------------------------------------------------------------------

def fetch_x_signal(query_terms):
    """
    Son 24 saatte contract adresi veya ticker gecen tweet sayisini ceker.
    X_BEARER_TOKEN yoksa bu adim atlanir (0 puan).
    """
    if not X_BEARER_TOKEN or not query_terms:
        return 0, 0

    query = " OR ".join(f'"{t}"' for t in query_terms if t)
    if not query:
        return 0, 0

    try:
        resp = requests.get(
            X_RECENT_COUNTS,
            params={"query": query, "granularity": "hour"},
            headers={"Authorization": f"Bearer {X_BEARER_TOKEN}"},
            timeout=20,
        )
        if resp.status_code != 200:
            print(f"[HATA] X API {resp.status_code}: {resp.text[:200]}")
            return 0, 0
        data = resp.json()
        counts = [pt.get("tweet_count", 0) for pt in data.get("data", [])]
        total = sum(counts)
        return total, len(counts)
    except Exception as e:
        print(f"[HATA] X API cekilemedi: {e}")
        return 0, 0


def evaluate_social(tweet_count):
    """0-20 puanlik sosyal skor. Cok az mention = organik olmayabilir/bilinmiyor,
    cok fazla ani patlama da pump grubu olabilir; orta-yukselen hacme puan verir."""
    if tweet_count <= 0:
        return 0, "X'te mention yok/olculemedi"
    if tweet_count < 5:
        return 5, f"X'te dusuk mention ({tweet_count})"
    if tweet_count < 50:
        return 15, f"X'te organik buyume ({tweet_count} tweet)"
    if tweet_count < 300:
        return 20, f"X'te guclu ilgi ({tweet_count} tweet)"
    return 10, f"X'te asiri/supheli hacim ({tweet_count} tweet) - dikkat"


# --------------------------------------------------------------------------
# 4) PIYASA/LIKIDITE SKORU
# --------------------------------------------------------------------------

def evaluate_market(pool):
    """0-40 puanlik piyasa skoru: mcap araligi, likidite, hacim, yaslilik."""
    score = 0
    notes = []

    mcap = pool["market_cap_usd"]
    if MIN_MARKET_CAP_USD <= mcap <= MAX_MARKET_CAP_USD:
        score += 15
        notes.append(f"mcap uygun aralikta (${mcap:,.0f})")
    else:
        notes.append(f"mcap aralik disi (${mcap:,.0f})")

    liq = pool["liquidity_usd"]
    if liq >= MIN_LIQUIDITY_USD:
        score += 15
        notes.append(f"likidite yeterli (${liq:,.0f})")
    else:
        notes.append(f"likidite dusuk (${liq:,.0f})")

    if liq > 0 and mcap > 0:
        ratio = liq / mcap
        if ratio > 0.15:
            score += 5
            notes.append("likidite/mcap orani saglikli")

    vol = pool["volume_24h_usd"]
    if vol > liq * 0.5 and vol > 0:
        score += 5
        notes.append(f"aktif hacim (${vol:,.0f})")

    return min(40, score), notes


# --------------------------------------------------------------------------
# 5) TELEGRAM
# --------------------------------------------------------------------------

def send_telegram_alert(pool, security_score, security_flags, market_score,
                         market_notes, social_score, social_note, total_score):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[UYARI] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID tanimli degil, mesaj atlanmadi ama console'a yaziliyor.")

    flags_txt = "\n".join(f"  - {f}" for f in security_flags) if security_flags else "  - kirmizi bayrak yok"
    notes_txt = "\n".join(f"  - {n}" for n in market_notes)

    text = (
        f"🔎 *ETH GEM RADAR SINYALI*\n\n"
        f"*{pool['name']}*\n"
        f"Kontrat: `{pool['contract_address']}`\n"
        f"Yas: {pool['age_hours']:.1f} saat\n"
        f"MCap: ${pool['market_cap_usd']:,.0f}\n"
        f"Likidite: ${pool['liquidity_usd']:,.0f}\n"
        f"24s Hacim: ${pool['volume_24h_usd']:,.0f}\n\n"
        f"*Skor: {total_score:.0f}/100*\n"
        f"- Guvenlik: {security_score}/40\n{flags_txt}\n"
        f"- Piyasa: {market_score}/40\n{notes_txt}\n"
        f"- Sosyal (X): {social_score}/20\n  - {social_note}\n\n"
        f"[DexScreener]({pool['dexscreener_url']}) | [GeckoTerminal]({pool['geckoterminal_url']})\n\n"
        f"⚠️ Bu bir yatirim tavsiyesi degildir, otomatik on-tarama sinyalidir. "
        f"Dusuk mcap tokenlerde rug-pull riski yuksektir, kendi arastirmani yap (DYOR)."
    )

    print("=" * 60)
    print(text)
    print("=" * 60)

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            resp = requests.post(
                url,
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": False,
                },
                timeout=20,
            )
            if resp.status_code != 200:
                print(f"[HATA] Telegram gonderim hatasi: {resp.text}")
        except Exception as e:
            print(f"[HATA] Telegram gonderilemedi: {e}")


# --------------------------------------------------------------------------
# ANA AKIS
# --------------------------------------------------------------------------

def main():
    print(f"[{datetime.now(timezone.utc).isoformat()}] Tarama basliyor...")
    state = load_state()
    sent_set = set(state.get("sent", []))

    raw_pools = fetch_new_pools()
    print(f"{len(raw_pools)} pool bulundu (GeckoTerminal).")

    candidates = []
    for raw in raw_pools:
        pool = parse_pool(raw)
        if not pool["contract_address"]:
            continue
        if pool["contract_address"] in sent_set:
            continue
        if pool["age_hours"] > MAX_POOL_AGE_HOURS:
            continue
        if not (MIN_MARKET_CAP_USD <= pool["market_cap_usd"] <= MAX_MARKET_CAP_USD):
            continue
        if pool["liquidity_usd"] < MIN_LIQUIDITY_USD:
            continue
        candidates.append(pool)

    print(f"{len(candidates)} aday on-filtreden gecti, guvenlik/sosyal analiz ediliyor...")

    alerts_sent = 0
    for pool in candidates:
        time.sleep(1)  # rate-limit nezaketi

        sec = fetch_security(pool["contract_address"])
        security_score, security_flags = evaluate_security(sec)

        # eger honeypot ise direkt ele, bosuna X/telegram harcama
        if "HONEYPOT" in security_flags:
            sent_set.add(pool["contract_address"])
            continue

        market_score, market_notes = evaluate_market(pool)

        symbol = pool["name"].split("/")[0].strip() if "/" in pool["name"] else pool["name"]
        tweet_count, _ = fetch_x_signal([pool["contract_address"], symbol])
        social_score, social_note = evaluate_social(tweet_count)

        total_score = security_score + market_score + social_score

        print(f"- {pool['name']} ({pool['contract_address'][:10]}...) -> skor: {total_score}/100")

        if total_score >= MIN_SCORE_TO_ALERT:
            send_telegram_alert(
                pool, security_score, security_flags,
                market_score, market_notes, social_score, social_note, total_score
            )
            alerts_sent += 1

        sent_set.add(pool["contract_address"])

    state["sent"] = list(sent_set)[-2000:]  # state dosyasi sisirmesin
    save_state(state)

    print(f"Tarama bitti. {alerts_sent} sinyal gonderildi.")


if __name__ == "__main__":
    main()
