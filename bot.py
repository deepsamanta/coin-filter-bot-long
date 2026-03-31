import requests
import time
import gspread
from google.oauth2.service_account import Credentials

from config import SHEET_ID 


# =====================================================
# CONFIG
# =====================================================

#SHEET_ID        = "your_sheet_id_here"
DROP_THRESHOLD = 15.0

# =====================================================
# GOOGLE SHEETS CONNECTION
# =====================================================

scope  = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds  = Credentials.from_service_account_file("service_account.json", scopes=scope)
client = gspread.authorize(creds)
sheet  = client.open_by_key(SHEET_ID).sheet1


# =====================================================
# COINDCX HELPERS
# =====================================================

def get_all_pairs():
    url = "https://api.coindcx.com/exchange/v1/derivatives/futures/data/active_instruments?margin_currency_short_name[]=USDT"
    return requests.get(url).json()


def pair_to_symbol(pair):
    return pair.replace("B-", "").replace("_", "")


def get_change_pct(pair, hours):
    url = "https://public.coindcx.com/market_data/candlesticks"
    now = int(time.time())
    params = {
        "pair":       pair,
        "from":       now - (hours * 3600),
        "to":         now,
        "resolution": "60",
        "pcode":      "f",
    }
    try:
        candles = sorted(
            requests.get(url, params=params, timeout=10).json()["data"],
            key=lambda x: x["time"]
        )
        if len(candles) < 2:
            return None
        open_price  = float(candles[0]["open"])
        close_price = float(candles[-1]["close"])
        return round(((close_price - open_price) / open_price) * 100, 2)
    except Exception:
        return None


# =====================================================
# STEP 1: SCAN ALL COINS → FILTER > 15% DROP (6H, 12H, 1D or 2D)
# =====================================================

def get_losers():
    pairs  = get_all_pairs()
    losers = []

    print(f"Scanning {len(pairs)} pairs for >{DROP_THRESHOLD}% drop (6H, 12H, 1D or 2D)...\n")

    for i, pair in enumerate(pairs):
        symbol = pair_to_symbol(pair)

        pct_6h = get_change_pct(pair, 6)
        pct_12h = get_change_pct(pair, 12)
        pct_1d  = get_change_pct(pair, 24)
        pct_2d  = get_change_pct(pair, 48)

        # Print all timeframes
        values = [pct_6h, pct_12h, pct_1d, pct_2d]
        if all(v is not None for v in values):
            print(f"[{i+1}/{len(pairs)}] {symbol:20s} → "
                  f"6H: {pct_6h:+.2f}%  |  "
                  f"12H: {pct_12h:+.2f}%  |  "
                  f"1D: {pct_1d:+.2f}%  |  "
                  f"2D: {pct_2d:+.2f}%")
        else:
            print(f"[{i+1}/{len(pairs)}] {symbol:20s} → no data")

        # Add if ANY timeframe shows >= 15% drop
        if (pct_6h  is not None and pct_6h  <= -DROP_THRESHOLD) or \
           (pct_12h is not None and pct_12h <= -DROP_THRESHOLD) or \
           (pct_1d  is not None and pct_1d  <= -DROP_THRESHOLD) or \
           (pct_2d  is not None and pct_2d  <= -DROP_THRESHOLD):
            losers.append(symbol)

        time.sleep(0.2)

    print(f"\n✅ Found {len(losers)} losers below -{DROP_THRESHOLD}%: {losers}\n")
    return losers


# =====================================================
# STEP 2: DELETE ROWS WHERE COLUMN B = "TP COMPLETED"
# =====================================================

def delete_tp_completed_rows():
    rows = sheet.get_all_values()

    for i in range(len(rows) - 1, -1, -1):
        col_b = str(rows[i][1]).strip().upper() if len(rows[i]) > 1 else ""
        if col_b == "TP COMPLETED":
            sheet.delete_rows(i + 1)
            print(f"[SHEET] Deleted row {i+1} ({rows[i][0]}) — TP COMPLETED")
            time.sleep(0.3)


# =====================================================
# STEP 3: ADD NEW COINS NOT ALREADY IN COLUMN A
# =====================================================

def add_new_losers(losers):
    rows = sheet.get_all_values()

    existing_symbols = set(
        str(row[0]).strip().upper()
        for row in rows if row and row[0]
    )

    print(f"[SHEET] Existing symbols: {existing_symbols}\n")

    added = []
    for symbol in losers:
        if symbol.upper() not in existing_symbols:
            sheet.append_row([symbol, ""])
            print(f"[SHEET] ➕ Added new coin: {symbol}")
            added.append(symbol)
            time.sleep(0.3)
        else:
            print(f"[SHEET] ⏭️  Already exists: {symbol}")

    return added


# =====================================================
# MAIN BOT
# =====================================================

def run_bot():
    print("=" * 50)
    print("🤖 BOT STARTED")
    print("=" * 50)

    losers = get_losers()

    if not losers:
        print("No losers found below threshold.")
        return

    print("\n--- Cleaning TP COMPLETED rows ---")
    delete_tp_completed_rows()

    print("\n--- Updating sheet with new losers ---")
    added = add_new_losers(losers)

    print("\n" + "=" * 50)
    print(f"✅ DONE — {len(added)} new coins added to sheet")
    for s in added:
        print(f"   🔴 {s}")
    print("=" * 50)


# =====================================================
# INFINITE LOOP — RUNS EVERY HOUR
# =====================================================

cycle = 1

while True:
    try:
        print(f"\n{'='*50}")
        print(f"🔁 CYCLE #{cycle}  |  {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*50}")

        run_bot()

        cycle += 1
        print(f"\n⏳ Sleeping 1 hour... next run at {time.strftime('%H:%M:%S', time.localtime(time.time() + 3600))}")
        time.sleep(3600)

    except Exception as e:
        print(f"\n❌ BOT ERROR: {e}")
        print("⏳ Retrying in 60 seconds...")
        time.sleep(60)