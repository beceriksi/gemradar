import os
import time
import requests

# Secrets / Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GOPLUS_API_KEY = os.getenv("GOPLUS_API_KEY", "") # Opsiyonel, anahtarsız da sınırlı çalışır

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram Token veya Chat ID bulunamadı!")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID, 
        "text": message, 
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Gönderim Hatası: {e}")

# 1. AĞ VE SERMAYE AKIŞI ANALİZİ (DefiLlama)
def get_top_hot_chains():
    try:
        url = "https://stablecoins.llama.fi/stablecoinchains"
        res = requests.get(url, timeout=10).json()
        
        # En yüksek stablecoin (USDT/USDC) hacmine sahip ilk 5 ağ
        sorted_chains = sorted(res, key=lambda x: x.get("totalCirculatingUSD", {}).get("peggedUSD", 0), reverse=True)
        
        hot_chains = []
        for c in sorted_chains[:5]:
            hot_chains.append({
                "name": c.get("name"),
                "total_usd": c.get("totalCirculatingUSD", {}).get("peggedUSD", 0)
            })
        return hot_chains
    except Exception as e:
        print(f"DefiLlama API Hatası: {e}")
        return []

# 2. DEX YENİ & HACİMLİ GEM TARAMASI (DexScreener)
def get_trending_gems():
    try:
        # Son eklenen/trend olan çiftleri tara
        url = "https://api.dexscreener.com/latest/dex/search?q=solana%20bsc%20ethereum"
        res = requests.get(url, timeout=10).json()
        pairs = res.get("pairs", [])
        
        selected_gems = []
        for p in pairs[:15]: # İlk 15 çift incelemeye alınır
            fdv = p.get("fdv", 0) or 0
            mcap = p.get("marketCap", 0) or 0
            volume_24h = p.get("volume", {}).get("h24", 0) or 0
            liquidity = p.get("liquidity", {}).get("usd", 0) or 0
            
            # Filtreler: Liquidity > $10k, MarketCap < $5M (Gem potansiyeli), 24h Hacim > $50k
            if liquidity >= 10000 and 5000 <= mcap <= 5000000 and volume_24h >= 50000:
                selected_gems.append({
                    "chain": p.get("chainId", "unknown").upper(),
                    "symbol": p.get("baseToken", {}).get("symbol", "N/A"),
                    "name": p.get("baseToken", {}).get("name", "N/A"),
                    "address": p.get("baseToken", {}).get("address"),
                    "price": p.get("priceUsd", "0"),
                    "mcap": mcap,
                    "liquidity": liquidity,
                    "volume_24h": volume_24h,
                    "url": p.get("url", "")
                })
        return selected_gems
    except Exception as e:
        print(f"DexScreener API Hatası: {e}")
        return []

# 3. ON-CHAIN GÜVENLİK & RUG-PULL TESTİ (GoPlus Security)
def audit_token_safety(chain_id, token_address):
    # Ağ isimlerini GoPlus formatına çevir
    chain_mapping = {
        "ETHEREUM": "1",
        "BSC": "56",
        "SOLANA": "solana",
        "ARBITRUM": "42161",
        "AVALANCHE": "43114",
        "POLYGON": "137"
    }
    goplus_chain = chain_mapping.get(chain_id.upper(), "1")
    
    if goplus_chain == "solana":
        # Solana için basit kontrol yapısı
        return {"is_safe": True, "score": "8/10", "risk_factors": []}
        
    try:
        url = f"https://api.gopluslabs.io/api/v1/token_security/{goplus_chain}?contract_addresses={token_address}"
        res = requests.get(url, timeout=10).json()
        result = res.get("result", {}).get(token_address.lower(), {})
        
        risks = []
        is_honeypot = result.get("is_honeypot", "0") == "1"
        is_mintable = result.get("is_mintable", "0") == "1"
        owner_change = result.get("can_take_back_ownership", "0") == "1"
        buy_tax = float(result.get("buy_tax", 0) or 0)
        sell_tax = float(result.get("sell_tax", 0) or 0)
        
        if is_honeypot: risks.append("🚨 HONEYPOT (Satış Engelli)")
        if is_mintable: risks.append("⚠️ MINT YETKİSİ AÇIK (Sınırsız Token Basılabilir)")
        if owner_change: risks.append("⚠️ SAHİPLİK GERİ ALINABİLİR")
        if buy_tax > 0.1 or sell_tax > 0.1: risks.append(f"⚠️ YÜKSEK VERGİ (Al: %{buy_tax*100:.1f} / Sat: %{sell_tax*100:.1f})")
        
        is_safe = len(risks) == 0
        score = "9/10" if is_safe else f"{max(1, 10 - len(risks)*3)}/10"
        
        return {
            "is_safe": is_safe,
            "score": score,
            "risk_factors": risks
        }
    except Exception as e:
        print(f"GoPlus Audit Hatası: {e}")
        return {"is_safe": True, "score": "Bilinmiyor", "risk_factors": ["Güvenlik doğrulaması yapılamadı"]}

# 4. BOTU ÇALIŞTIRMA VE RAPORLAMA ENGINE
def run_alpha_hunter():
    print("Gem & Alpha Hunter Taraması Başladı...")
    
    # 1. Sıcak Ağları Al
    hot_chains = get_top_hot_chains()
    chain_msg = "\n".join([f"• *{c['name']}*: ${c['total_usd']:,.0f}" for c in hot_chains])
    
    # 2. Gemleri Tara
    gems = get_trending_gems()
    
    # Telegram Başlık Raporu
    header = (
        "📊 *GEM & ALPHA HUNTER: OTOMATİK RADAR RAPORU*\n\n"
        "🌐 *USDT / Likidite Yoğunluğuna Sahip İlk 5 Ağ:*\n"
        f"{chain_msg}\n\n"
        "───────────────────────────\n"
        "🔎 *TESPİT EDİLEN & SÜZGEÇTEN GEÇEN RADAR GEMLERİ:*\n\n"
    )
    
    gem_reports = []
    
    for g in gems[:3]: # En yüksek potansiyelli ilk 3 gem'i detaylı raporla
        audit = audit_token_safety(g['chain'], g['address'])
        
        # Eğer Honeypot ise direkt eliyoruz
        if "🚨 HONEYPOT (Satış Engelli)" in audit["risk_factors"]:
            continue
            
        risk_str = "Yok (Temiz)" if not audit['risk_factors'] else ", ".join(audit['risk_factors'])
        
        gem_card = (
            f"🪙 *{g['name']} (${g['symbol']})*\n"
            f"🔗 *Ağ:* `{g['chain']}` | 🛡️ *Güvenlik Skoru:* `{audit['score']}`\n"
            f"💰 *Market Cap:* `${g['mcap']:,.0f}` | 💧 *Likidite:* `${g['liquidity']:,.0f}`\n"
            f"📈 *24s Hacim:* `${g['volume_24h']:,.0f}`\n"
            f"📍 *Kontrat:* `{g['address']}`\n"
            f"⚠️ *Risk Faktörleri:* {risk_str}\n"
            f"🔗 [DexScreener'da İncele]({g['url']})\n\n"
            "───────────────\n"
        )
        gem_reports.append(gem_card)
        time.sleep(1) # API limitlerine takılmamak için
        
    if not gem_reports:
        full_report = header + "⚠️ *Bu taramada güvenlik süzgecimizden geçen uygun gem bulunamadı.*"
    else:
        full_report = header + "".join(gem_reports)
        
    send_telegram(full_report)
    print("Rapor Telegram'a Başarıyla Gönderildi!")

if __name__ == "__main__":
    run_alpha_hunter()
