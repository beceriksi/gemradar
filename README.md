# ETH Gem Radar → Telegram Bot

Ethereum'da yeni acilan, dusuk piyasa degerli ama guvenlik + likidite + X
(Twitter) sosyal sinyali saglam olan token'lari tarayip Telegram'a bildirim
atan, GitHub Actions uzerinde ucretsiz calisan bir bot.

## Nasil calisir?

1. **Kesif**: GeckoTerminal API'den Ethereum'daki en yeni pool'lar cekilir.
2. **On-filtre**: piyasa degeri / likidite / yas araligina gore elenir.
3. **Guvenlik**: GoPlus Security API ile honeypot, mint yetkisi, gizli owner,
   yuksek vergi, owner/creator arz yogunlugu kontrol edilir (40 puan).
4. **Piyasa**: mcap araligi, likidite/mcap orani, 24s hacim (40 puan).
5. **Sosyal**: X API ile son 24 saatteki contract adresi/ticker mention
   sayisi olculur (20 puan).
6. Toplam skor `MIN_SCORE_TO_ALERT` (varsayilan 70/100) uzerindeyse
   Telegram'a sinyal gonderilir.
7. Gonderilen adresler `sent_tokens.json` icinde tutulur, ayni token'a
   tekrar sinyal atilmaz. Bu dosya her calistirmada otomatik repoya commitlenir.

**Onemli**: Bu bot bir yatirim tavsiyesi motoru degildir. Ciktisi bir
on-tarama/filtreleme sinyalidir. Dusuk piyasa degerli tokenlerde rug-pull ve
manipulasyon riski cok yuksektir. Skorun yuksek olmasi "guvenli" anlamina
gelmez — sadece belirlenen kriterlere gore digerlerinden daha az riskli
gorunuyor demektir. Nihai karar ve risk tamamen sana aittir.

## Kurulum

### 1) Bu klasoru GitHub'a pushla

```bash
cd eth-gem-radar
git init
git add .
git commit -m "ilk kurulum"
git branch -M main
git remote add origin https://github.com/KULLANICI_ADIN/eth-gem-radar.git
git push -u origin main
```

### 2) Telegram bot olustur

1. Telegram'da **@BotFather**'a git, `/newbot` yaz, ismini ver.
2. Sana verdigi **bot token**'i kopyala (`TELEGRAM_BOT_TOKEN`).
3. Botu mesaj atacagi bir gruba/kanala ekle (veya kendi DM'inle konustur).
4. **Chat ID**'ni ogrenmek icin: bota bir mesaj at, sonra tarayicida ac:
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
   Donen JSON'da `chat.id` alanini bul (`TELEGRAM_CHAT_ID`).
   Kanal kullaniyorsan chat id genelde `-100...` ile baslar.

### 3) X (Twitter) API erisimi

X Developer Portal'dan (developer.x.com) bir proje/app olustur, **Bearer
Token** al. `tweets/counts/recent` endpoint'i icin en az **Basic** ucretli
plan gerekiyor (Free tier bu endpoint'e izin vermiyor).

### 4) GitHub Secrets ekle

Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret adi | Aciklama |
|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather'dan aldigin token |
| `TELEGRAM_CHAT_ID` | Mesajin gidecegi chat/kanal ID'si |
| `X_BEARER_TOKEN` | X API Bearer Token |

### 5) Workflow'u aktif et

`.github/workflows/scan.yml` dosyasi her 15 dakikada bir otomatik
calisacak sekilde ayarli (GitHub cron, UTC, bazen birkac dk gecikebilir).
Ilk testi manuel tetiklemek icin:

**Actions** sekmesi → **ETH Gem Radar Scan** → **Run workflow**.

## Ayarlari degistirme

`.github/workflows/scan.yml` icindeki `env` blogundan esikleri
degistirebilirsin:

- `MIN_MARKET_CAP_USD` / `MAX_MARKET_CAP_USD` — piyasa degeri araligi
- `MIN_LIQUIDITY_USD` — minimum likidite
- `MAX_POOL_AGE_HOURS` — kac saatten yeni pool'lar taransin
- `MIN_SCORE_TO_ALERT` — kac puan uzeri sinyal atsin (0-100)

Tarama sikligini degistirmek icin `scan.yml` icindeki `cron: "*/15 * * * *"`
satirini duzenle (orn. her 5 dk icin `*/5 * * * *`).

## Yerel test

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=xxx
export TELEGRAM_CHAT_ID=xxx
export X_BEARER_TOKEN=xxx
python gem_scanner.py
```

## Genisletme fikirleri

- Claude/GPT API ile website + X biyografisi ozetleyip "anlati/ekip"
  hakkinda otomatik risk notu ekleme.
- Etherscan API ile holder dagilimini daha derin analiz etme.
- Birden fazla chain (BSC, Base, Arbitrum) icin GeckoTerminal network
  parametresini cogaltma (`eth` -> `bsc`, `base`, ...).
- Telegram butonlariyla "izle / gec" gibi interaktif filtreleme.
