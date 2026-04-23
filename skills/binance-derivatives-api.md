# Skill: Binance Derivatives API

**Tanggal:** 2026-04-23
**Source:** https://developers.binance.com/docs/derivatives/
**Trigger:** Butuh ambil data pasar futures/options, trading bot, atau integrasi Binance derivatives

---

## 1. Peta Produk (sitemap hasil scan 533 pages)

| Produk | Pages | REST Base | WebSocket Base |
|--------|-------|-----------|----------------|
| **USDⓈ-M Futures** (perpetual & quarterly, USDT/USDC margin) | 168 | `https://fapi.binance.com` | `wss://fstream.binance.com` |
| **COIN-M Futures** (perpetual & quarterly, coin margin) | 121 | `https://dapi.binance.com` | `wss://dstream.binance.com` |
| **Options** (European, USDT-settled) | 77 | `https://eapi.binance.com` | `wss://fstream.binance.com/{public,market,private}/` |
| **Portfolio Margin (Classic PM)** | 130 | `https://papi.binance.com` | `wss://fstream.binance.com/pm/` |
| **Portfolio Margin Pro** | 33 | `https://papi.binance.com` | PM-Pro dedicated user-data-stream |

### Testnet URLs

| Produk | REST Testnet | WSS Testnet |
|--------|--------------|-------------|
| USDⓈ-M | `https://demo-fapi.binance.com` | `wss://fstream.binancefuture.com` |
| COIN-M | `https://testnet.binancefuture.com` | `wss://dstream.binancefuture.com` |
| Options | `https://testnet.binancefuture.com` | `wss://fstream.binancefuture.com/{public,market,private}/` |
| Portfolio Margin | (tidak ada testnet dedicated) | — |

## 2. Struktur Kategori per Produk

### USDⓈ-M Futures (168 pages)
| Kategori | Endpoints |
|----------|-----------|
| `account/rest-api` | 23 (Account Info V2/V3, Balance V2/V3, Leverage Brackets, BNB Burn, Transfer, Income History, Commission Rate, etc.) |
| `account/websocket-api` | 4 |
| `market-data/rest-api` | 35 (Kline, Order Book, Ticker, Funding Rate, Mark Price, Open Interest, Basis, Long/Short Ratio, Delivery Price, etc.) |
| `market-data/websocket-api` | 3 |
| `trade/rest-api` | 32 (New/Modify/Cancel Order, Algo Orders, Position Info V2/V3, Margin Type, Leverage, Position Mode, TradFi Perps, etc.) |
| `trade/websocket-api` | 8 |
| `user-data-streams` | event stream (listenKey-based) |
| `websocket-market-streams` | aggTrade, kline, ticker, depth, markPrice, liquidation, contractInfo, tradingSession, etc. |
| `convert` | Convert endpoints |
| `portfolio-margin-endpoints` | PM-related futures endpoints |

### COIN-M Futures (121 pages)
Similar structure ke USDⓈ-M tapi lebih ramping:
- `account/rest-api`: 15, `trade/rest-api`: 22, `market-data/rest-api`: 27
- Additional streams: Index Price, Mark Price of All Symbols of a Pair

### Options (77 pages)
| Kategori | Endpoints |
|----------|-----------|
| `account` | Option-Margin-Account-Information, Funds-Transfer, Account-Funding-Flow |
| `market-data` | Exchange Info, Order Book, Kline, Historical Exercise, Option Mark Price, Recent Block Trade |
| `trade` | New/Cancel Order, Position Info, Exercise Record, Commission |
| `market-maker-endpoints` | Auto-Cancel heartbeat, MMP (Market Maker Protection) config |
| `market-maker-block-trade` | RFQ-style block trading |
| `user-data-streams` | Greek Update, Risk Level Change, Balance/Position/Order Updates |
| `websocket-market-streams` | 24h ticker, Book Ticker, Index Price, Mark Price, Open Interest, Diff Depth |

### Portfolio Margin (130 pages)
Meng-kombinasi UM (USDⓈ-M), CM (COIN-M), Margin, dan Options under satu akun.
- Order types punya prefix `UM-` atau `CM-`: `New-UM-Order`, `New-CM-Order`, `New-Margin-Order`
- Algo orders: `New-UM-Algo-Order`
- Conditional orders: `New-UM-Conditional-Order`, `New-CM-Conditional-Order`
- PM-specific: Auto-repay, Fund-Collection, Margin Borrow/Repay, BNB Transfer, PM-TradFi-Perps

### Portfolio Margin Pro (33 pages)
Level lebih tinggi dari Classic PM — bankruptcy loan, margin call level, delta mode, tiered collateral rate, LDUSDT transfer.

## 3. Authentication

### API Key Header
```
X-MBX-APIKEY: <your-api-key>
```

### 3 Jenis Signature (pilih salah satu)

#### A. HMAC SHA256 (paling umum)
```bash
SECRET="your-secret-key"
QUERY="symbol=BTCUSDT&side=BUY&type=LIMIT&quantity=1&price=9000&timeInForce=GTC&recvWindow=5000&timestamp=$(date +%s000)"
SIG=$(echo -n "$QUERY" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')
curl -H "X-MBX-APIKEY: $APIKEY" -X POST "https://fapi.binance.com/fapi/v1/order?$QUERY&signature=$SIG"
```

#### B. RSA (PKCS#8, SHA256 + base64 + URL-encode)
```bash
QUERY="timestamp=1671090801999&recvWindow=9999999&symbol=BTCUSDT&side=SELL&type=MARKET&quantity=1.23"
SIG=$(echo -n "$QUERY" | openssl dgst -keyform PEM -sha256 -sign ./rsa-prv.pem | openssl enc -base64 | tr -d '\n')
# Harus URL-encode karena ada /, +, = di output base64
```

#### C. Ed25519 (didukung, tercepat untuk signing)
Upload public key Ed25519 di dashboard → dapat API key.

### Security Types (wajib dipahami)
| Type | Butuh API Key? | Butuh Signature? |
|------|---------------|-------------------|
| `NONE` | ❌ | ❌ |
| `MARKET_DATA` | ✅ | ❌ |
| `USER_STREAM` | ✅ | ❌ |
| `USER_DATA` (SIGNED) | ✅ | ✅ |
| `TRADE` (SIGNED) | ✅ | ✅ |

### Timing Security
- Wajib param `timestamp` (ms epoch)
- Optional `recvWindow` (default 5000ms, **rekomendasi ≤5000**)
- Logic server:
  ```
  if (timestamp < serverTime + 1000 && serverTime - timestamp <= recvWindow) OK
  else REJECT
  ```
- Sync time dulu via `GET /fapi/v1/time` kalau clock drift mencurigakan

## 4. Rate Limits

### Headers yang Dikembalikan
- `X-MBX-USED-WEIGHT-(intervalNum)(intervalLetter)` — IP-based weight
- `X-MBX-ORDER-COUNT-(intervalNum)(intervalLetter)` — order count per account

### HTTP Status Codes
| Code | Arti | Action |
|------|------|--------|
| 4xx | Client error | Fix request |
| 403 | WAF violation | Cek payload |
| 408 | Backend timeout | Retry |
| 429 | Rate limit | **BACKOFF WAJIB** |
| 418 | Auto-ban (abis nge-spam 429) | Tunggu 2min–3 hari |
| 503 "Unknown error" | Execution unknown | **VERIFY via WebSocket/orderId query sebelum retry** |
| 503 "Service Unavailable" | Failure pasti | Exponential backoff (200→400→800ms) |
| 503 "-1008" | System overload | Reduce concurrency. Reduce-only/close orders exempt |
| 5xx | Server error | Retry |

### Error Format
```json
{ "code": -1121, "msg": "Invalid symbol." }
```

### IP vs Account
- Rate limit di-track per **IP**, bukan per API key
- Order rate limit di-track per **account**
- Prefer WebSocket untuk data streaming (bukan REST polling) biar hemat weight

## 5. Request Format Gotchas

- GET → param WAJIB di query string
- POST/PUT/DELETE → bisa query string ATAU body (`application/x-www-form-urlencoded`), BOLEH dicampur
- Kalau dicampur dan ada key sama → **query string menang**
- Signature WAJIB paling akhir di query/body
- `totalParams` (yang di-sign) = `queryString + requestBody` concatenated
- Param boleh any order, tapi URL-encoded value

## 6. WebSocket Details

### Market Streams (public, no auth)
```
wss://fstream.binance.com/ws/btcusdt@aggTrade
wss://fstream.binance.com/stream?streams=bnbusdt@aggTrade/btcusdt@markPrice
```

### User Data Streams (butuh listenKey)
```
# 1. Request listenKey via REST
POST /fapi/v1/listenKey (header: X-MBX-APIKEY)
# 2. Connect WebSocket dengan listenKey
wss://fstream.binance.com/ws/<listenKey>
# 3. Keepalive tiap 60 menit
PUT /fapi/v1/listenKey
# 4. Close saat selesai
DELETE /fapi/v1/listenKey
```

### Options User Data Stream
```
wss://fstream.binance.com/private/ws/<listenKey>
```

### Portfolio Margin User Data Stream
```
wss://fstream.binance.com/pm/ws/<listenKey>
```

## 7. Key Endpoints Reference (yang paling sering dipakai)

### USDⓈ-M Futures Quick Reference
| Action | Endpoint | Security |
|--------|----------|----------|
| Server time | `GET /fapi/v1/time` | NONE |
| Exchange info | `GET /fapi/v1/exchangeInfo` | NONE |
| Kline | `GET /fapi/v1/klines` | NONE |
| Order book | `GET /fapi/v1/depth` | NONE |
| Mark price | `GET /fapi/v1/premiumIndex` | NONE |
| Funding rate | `GET /fapi/v1/fundingRate` | NONE |
| Open interest | `GET /fapi/v1/openInterest` | NONE |
| Account balance V3 | `GET /fapi/v3/balance` | USER_DATA |
| Account info V3 | `GET /fapi/v3/account` | USER_DATA |
| Position info V3 | `GET /fapi/v3/positionRisk` | USER_DATA |
| New order | `POST /fapi/v1/order` | TRADE |
| Cancel order | `DELETE /fapi/v1/order` | TRADE |
| Change leverage | `POST /fapi/v1/leverage` | TRADE |
| Change margin type | `POST /fapi/v1/marginType` | TRADE |
| Income history | `GET /fapi/v1/income` | USER_DATA |

### COIN-M counterparts gunakan `/dapi/v1/...` dengan route nama sama

### Options Quick Reference
| Action | Endpoint |
|--------|----------|
| Exchange info | `GET /eapi/v1/exchangeInfo` |
| Order book | `GET /eapi/v1/depth` |
| Mark price | `GET /eapi/v1/mark` |
| New order | `POST /eapi/v1/order` |
| Position info | `GET /eapi/v1/position` |

### Portfolio Margin Quick Reference
| Action | Endpoint |
|--------|----------|
| Account info | `GET /papi/v1/account` |
| UM new order | `POST /papi/v1/um/order` |
| CM new order | `POST /papi/v1/cm/order` |
| Margin new order | `POST /papi/v1/margin/order` |
| UM position | `GET /papi/v1/um/positionRisk` |

## 8. SDK Resmi (dari pages official)
```bash
# Python
pip install binance-sdk-derivatives-trading-usds-futures
# atau meta-connector:
pip install binance-connector
# repo: https://github.com/binance/binance-connector-python

# Java
git clone https://github.com/binance/binance-connector-java.git
```

## 9. Gotchas & Best Practices

1. **Clock sync wajib** — drift >1s bikin semua signed request di-reject
2. **recvWindow kecil** — 3000-5000ms, jangan pakai 60000 (security risk)
3. **503 "Unknown error" ≠ failure** — jangan langsung retry order, verify dulu via position/orderId
4. **Reduce-only/close exempt dari -1008** — manfaatkan untuk emergency close saat overload
5. **Testnet API key ≠ mainnet** — beda endpoint, beda key
6. **POST /order WAJIB cek response** untuk `orderId` sebelum assume sukses
7. **Idempotency**: pakai `newClientOrderId` (custom UUID) supaya retry aman — kalau retry dengan clientOrderId sama, server return duplicate error instead of bikin 2 order
8. **Batch orders** (`POST /fapi/v1/batchOrders`) — max 5 orders per request, tiap order tetap kena rate limit weight
9. **Hedge mode vs One-way mode** (`positionSide`: `BOTH`/`LONG`/`SHORT`) — set sekali di account config
10. **`priceProtect`** — aktifin buat STOP/TAKE_PROFIT supaya auto-reject kalau price vs mark price terlalu jauh
11. **Orderbook local maintenance**: kalau build local orderbook dari diff depth stream, IKUTI guide "How to manage a local order book correctly" (snapshot + apply diffs dengan first_update_id check)

## 10. Python Example (signed request manual, tanpa SDK)

```python
import time, hmac, hashlib, requests
from urllib.parse import urlencode

API_KEY = "..."
SECRET  = "..."
BASE    = "https://fapi.binance.com"

def signed_request(method, path, params=None):
    params = params or {}
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000
    qs = urlencode(params)
    sig = hmac.new(SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()
    url = f"{BASE}{path}?{qs}&signature={sig}"
    r = requests.request(method, url, headers={"X-MBX-APIKEY": API_KEY})
    return r.json()

# Get account balance V3
print(signed_request("GET", "/fapi/v3/balance"))

# Place order
print(signed_request("POST", "/fapi/v1/order", {
    "symbol":      "BTCUSDT",
    "side":        "BUY",
    "type":        "LIMIT",
    "timeInForce": "GTC",
    "quantity":    0.001,
    "price":       50000,
    "newClientOrderId": "my-uuid-1234",
}))
```

## 11. Resource Map (Full URL Index)

File `/tmp/binance-map/derivatives-urls.txt` (533 URLs) ada di local cache saat scan.
Struktur kategori lengkap di `/tmp/binance-map/endpoints-per-category.txt`.

Kalau butuh detail endpoint specific, fetch URL: `https://developers.binance.com/docs/derivatives/<product>/<category>/<endpoint-name>`

Contoh:
- https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Order
- https://developers.binance.com/docs/derivatives/options-trading/trade/New-Order

## Status

✅ Full sitemap scanned, general-info per produk diekstrak — 2026-04-23
