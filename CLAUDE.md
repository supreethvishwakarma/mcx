# MCX Commodity AI — CLAUDE.md

Intraday MCX commodity options paper-trading system for **CRUDEOIL, SILVER, GOLD**. Ported from a sibling NIFTY-index-options project (same ML/dashboard architecture) and retargeted at MCX via Angel One SmartAPI. Collects live ticks, trains XGBoost ML models, scores trade signals, and presents everything through a Next.js dashboard backed by a Flask API.

**This document is accurate as of the initial port. Read the "What's genuinely working vs. not yet wired" section below before trusting any claim elsewhere in this file.**

---

## Stack

| Layer | Tech |
|---|---|
| Frontend | Next.js 16 + React 19 + Tailwind v4 + Recharts |
| Backend API | Flask (Python 3.11+), SSE stream at `/api/stream` |
| Database | PostgreSQL (TimescaleDB extension optional — falls back to plain tables) |
| ML | XGBoost + LightGBM (scikit-learn pipeline), joblib `.pkl` models |
| Data Feed | TrueData REST + WebSocket (MCX segment — **unverified**, see caveats) |
| Broker | Angel One SmartAPI (order execution + instrument master) |
| Runtime | Linux/macOS, Python venv at `.venv/`, Node in `dashboard/node_modules/` |

---

## What's genuinely working vs. not yet wired

Built and verified locally this session (backend boots, dashboard boots, paper trade enter/exit round-trips correctly):

- Flask API + Next.js dashboard, both boot and serve on localhost
- Paper trading (manual entry/exit) — same engine as the NIFTY app, unchanged
- Angel One order-placement adapter (`broker/angelone_adapter.py`) — REST-based, untested against the live API
- **`data/angel_master_contract.py`** — downloads Angel One's live instrument master and resolves real CRUDEOIL/SILVER/GOLD option contracts (symbol, token, strike, lot size, tick size, expiry) into `symbol_master`. This is the one piece with no NIFTY equivalent — it exists because MCX has no fixed strike gap or expiry cadence to hardcode. Symbol-construction formulas, the download URL, and MCX order-routing conventions were verified against `marketcalls/openalgo` (a mature, multi-broker open-source platform with real production MCX support) — not guessed.
- **`backtest/mcx_option_resolver.py`** — expiry/strike/premium resolution against `symbol_master`, replacing the NIFTY app's `backtest/option_resolver.py` (which assumed a fixed ₹50 strike gap and weekly Tuesday expiry — neither holds for MCX)
- IST market-hours handling, extended to MCX's 9:00 AM–11:30 PM session (see `config/settings.py` `MARKET_OPEN_*`/`MARKET_CLOSE_*`)

**Not yet done — real, known gaps, not hidden:**

- **No live market data feed configured.** TrueData's MCX symbol conventions (`TD_MCX_FUTURES_SYMBOLS` in `config/settings.py`) are a best guess, not verified against a live TrueData account. Confirm the actual MCX continuous-futures symbol names before relying on them.
- **No trained ML models.** `models/saved/*.pkl` don't exist — `models_loaded` will show `false` until you train on real data. Per this project's own inherited rule (see `models/train_model.py`'s docstring), never train on synthetic/mock data.
- **Single-underlying scanner.** `backend/app.py`'s live scan loop tracks ONE underlying at a time (`config.settings.PRIMARY_UNDERLYING`, default `CRUDEOIL`) — same single-symbol architecture the NIFTY app had. To trade SILVER or GOLD instead, change `MCX_PRIMARY_UNDERLYING` in `.env` and restart. Simultaneous multi-underlying scanning would need `scan_market()` and the tick-monitor loop generalized to iterate `SYMBOLS` — a real rewrite, not done here.
- **Strategy/signal thresholds are inherited from NIFTY, not recalibrated.** `strategy/signal_generator.py`, `strategy/trade_scorer.py`, and the risk-profile SL/target percentages were tuned against months of NIFTY options backtesting (see the sibling project's own hard-won lessons). None of that tuning transfers to CRUDEOIL/SILVER/GOLD price behavior — treat every threshold as a starting point to re-backtest, not a verified default.
- **Peripheral scripts** (`scripts/train_dqn_exit.py`, `scripts/train_rl_exit.py`, `scripts/tick_replay_backtest.py`, and others) still import the old `backtest.option_resolver` in places and reference NIFTY conventions internally — they were not individually re-verified for MCX in this port. Expect to adapt them before use.
- **Physical settlement risk is flagged but not yet enforced.** `backtest/mcx_option_resolver.is_within_physical_settlement_window()` exists but nothing currently calls it to force-close positions or block new entries automatically — wire it into `OrderManager`/`scan_market()` before trading anything close to expiry. See "What NOT To Do" below.

---

## Directory Structure

```
mcx-commodity-ai/
├── backend/app.py                    # Flask API server (port 5050) — the main backend
├── dashboard/                        # Next.js frontend (port 3000)
│   └── app/{live,charts,backtest,trades,ai,settings}/
├── data/
│   ├── angel_master_contract.py      # NEW — MCX instrument master resolver (see above)
│   ├── truedata_adapter.py           # TrueData REST + WebSocket client (MCX symbols unverified)
│   ├── market_stream.py              # Angel One SmartWebSocket V2 (exchange code MCX=5)
│   └── tick_collector.py
├── broker/
│   ├── angelone_adapter.py           # Angel One SmartAPI order execution
│   ├── base_adapter.py               # Broker-agnostic interface
│   ├── paper_adapter.py              # Simulated trades (default)
│   └── order_manager.py
├── backtest/
│   ├── mcx_option_resolver.py        # NEW — MCX expiry/strike/premium resolution
│   ├── option_resolver.py            # OLD — NIFTY-only, kept for scripts not yet migrated
│   └── backtest_engine.py
├── strategy/                         # Signal generation, scoring, regime detection — thresholds inherited from NIFTY, unverified for commodities
├── models/                           # MacroModelTrainer/MicroModelTrainer, RL exit agent — no trained .pkl files yet
├── config/
│   ├── settings.py                   # SYMBOLS, PRIMARY_UNDERLYING, MCX market hours, Angel One env vars
│   └── risk_profiles.py              # LOW/MEDIUM/HIGH — SL/target % inherited from NIFTY, not recalibrated
├── database/schema.sql               # symbol_master table now holds MCX contracts (underlying/expiry/strike/CE-PE/lot_size)
└── scripts/                          # Backfill, training, backtest scripts — not all individually re-verified for MCX
```

---

## How to Run (localhost)

### Prerequisites
```bash
# PostgreSQL running locally (TimescaleDB extension optional)
sudo service postgresql start   # or brew services start postgresql on macOS
createdb mcx_trading

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`requirements.txt` pins `pandas-ta-classic` (not `pandas-ta` — see the comment in that file for why) and needs a one-line shim so `import pandas_ta` resolves to it:
```bash
echo "from pandas_ta_classic import *" > $(.venv/bin/python -c "import site; print(site.getsitepackages()[0])")/pandas_ta.py
```

### Configure
```bash
cp .env.example .env
# Fill in DB_*, ANGEL_ONE_* (see broker/angelone_adapter.py docstring), and
# TRUEDATA_USER/TRUEDATA_PASSWORD if you have them.
PGPASSWORD=<yours> psql -h localhost -U postgres -d mcx_trading -f database/schema.sql
```

### Resolve the MCX option chain (do this before expecting real symbols/lot sizes)
```bash
.venv/bin/python -m data.angel_master_contract
# Or a single underlying:
.venv/bin/python -m data.angel_master_contract --underlying CRUDEOIL
```

### Run
```bash
.venv/bin/python backend/app.py          # http://localhost:5050
cd dashboard && npm install && npm run dev   # http://localhost:3000 (separate terminal)
```

Paper trading (`TRADE_MODE=paper`, the default) works immediately with no broker credentials — enter/exit trades manually from the dashboard, or `POST /api/paper/enter`. Live signal scanning needs real candle data in `minute_candles` for `PRIMARY_UNDERLYING`'s continuous-futures symbol, which needs a working TrueData or Angel One feed connected — neither is configured by default.

---

## MCX-Specific Facts (verified via web research + OpenAlgo's source, cross-check before trusting for real capital)

- **Trading hours**: 9:00 AM – 11:30 PM IST (11:55 PM in the US winter DST window), Mon–Fri. Far longer than NSE's 9:15–3:30 — see "What NOT To Do" for the UTC/IST bug this class of session length makes worse.
- **Settlement**: CRUDEOIL/SILVER/GOLD options are **physically/deliverable settled** near expiry — unlike NIFTY's cash-settled index options, holding into the last few sessions risks a real commodity delivery obligation. `PHYSICAL_SETTLEMENT_CUTOFF_DAYS` (default 3) exists in `config/settings.py` but nothing enforces it yet (see gaps above).
- **Lot sizes, strike intervals, expiry dates**: all revised periodically by the exchange — never hardcoded anywhere in this codebase. Always resolved live via `data/angel_master_contract.py` → `symbol_master`. If `get_lot_size()`/`get_atm_strike()` can't find rows, re-run the master-contract script rather than assuming a stale fallback constant is correct.
- **Angel One instrument master**: `https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json` — MCX options use `instrumenttype == "OPTFUT"`, `exch_seg == "MCX"`. Symbol format: `{NAME}{DDMMMYY}{STRIKE}{CE|PE}` (e.g. `CRUDEOIL19SEP265800CE`); raw `strike` and `tick_size` fields are ×100 of the real value.
- **Order routing**: same producttype convention as NFO — `INTRADAY` for MIS-equivalent, `CARRYFORWARD` for NRML-equivalent. `broker/angelone_adapter.py`'s existing `_PRODUCT_MAP` already handles this correctly; no MCX-specific change was needed there (verified against OpenAlgo's `broker/angel/mapping/order_data.py`).

---

## What NOT To Do

- **Don't hardcode MCX lot sizes, strike gaps, or expiry dates anywhere.** This is the single lesson most directly inherited (and most directly relevant) from the NIFTY app's own history: it had a real production bug from hardcoding NSE expiry-day assumptions. MCX has no fixed weekday/monthly-date pattern either — always resolve from `symbol_master` via `data/angel_master_contract.py`.
- **Don't let a position ride into the physical-settlement window unmonitored.** Wire `is_within_physical_settlement_window()` into the exit logic before trusting this for anything beyond paper trading — a MCX options position held to physical settlement is a real commodity delivery obligation, not a benign expiry.
- **Don't trust `datetime.now()` for market-hours checks without going through `utils.helpers.now_ist()`.** The sibling NIFTY project had a real bug here: on any UTC-clocked host (cloud containers, CI), naive `datetime.now()` silently shifts the market-hours window by 5:30 IST. MCX's 9:00 AM–11:30 PM session makes this worse, not better — it now spans a UTC midnight rollover, so date-boundary logic ("today's ticks") needs the same care.
- **Don't train macro/micro/RL models on synthetic or mock data**, even to make a dashboard indicator look "loaded." `models/train_model.py`'s own docstring says real data only — this was deliberately preserved rather than routed around during the port.
- **Don't assume `strategy/`'s NIFTY-tuned gates and thresholds transfer to commodities.** Re-backtest before trusting a score threshold, SL%, or target% for CRUDEOIL/SILVER/GOLD.
- **Don't assume TrueData's MCX symbol names in `config/settings.py` are correct** — they're an unverified best guess. Confirm against a real TrueData account (or Angel One's own market data) before relying on live candles.

---

## Environment Variables (.env)

```env
# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=mcx_trading
DB_USER=postgres
DB_PASSWORD=postgres

# Angel One SmartAPI (broker/angelone_adapter.py)
ANGEL_ONE_API_KEY=
ANGEL_ONE_CLIENT_ID=
ANGEL_ONE_PASSWORD=
ANGEL_ONE_TOTP_SECRET=

# TrueData (optional — for live candles; MCX symbol names unverified)
TRUEDATA_USER=
TRUEDATA_PASSWORD=

# MCX-specific
MCX_PRIMARY_UNDERLYING=CRUDEOIL          # CRUDEOIL | SILVER | GOLD
PHYSICAL_SETTLEMENT_CUTOFF_DAYS=3
TRADE_MODE=paper                          # paper | angelone
```
