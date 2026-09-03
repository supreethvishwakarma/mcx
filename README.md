# MCX Commodity AI — Options Trading Research System

> Full-stack intraday **options trading research platform for MCX commodities (CRUDEOIL, SILVER, GOLD)** — XGBoost + RL ML pipeline, paper trading, Angel One SmartAPI execution, and a live retro-terminal dashboard.

Ported from a sibling NIFTY-index-options project (same dashboard/ML/backtest architecture) and retargeted at MCX. See **[CLAUDE.md](./CLAUDE.md)** for the full technical reference, including an honest breakdown of what's genuinely working vs. what still needs wiring before it's real-money ready.

## Important Disclaimer

This software is an algorithmic trading research and execution platform intended for educational, research, and controlled paper trading use. MCX commodity options are **physically/deliverable settled** near expiry, unlike NIFTY's cash-settled index options — see [CLAUDE.md](./CLAUDE.md) for the settlement-risk safeguard that exists but is not yet enforced. Nothing here is investment advice.

## What this is

- Paper-trades CRUDEOIL, SILVER, and GOLD options via a signal pipeline (technical indicators → XGBoost scoring → risk-managed entry/exit)
- Resolves real MCX option contracts (symbol, strike, lot size, expiry) live from Angel One's instrument master — nothing about MCX contract specs is hardcoded, since the exchange revises them periodically
- Same Next.js dashboard as the sibling NIFTY project: live trade suggestions, option chain, candle charts, backtest runner, trade history

## Quick Start (localhost)

```bash
# 1. Database
sudo service postgresql start
createdb mcx_trading

# 2. Python
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
echo "from pandas_ta_classic import *" > $(.venv/bin/python -c "import site; print(site.getsitepackages()[0])")/pandas_ta.py

# 3. Configure
cp .env.example .env   # fill in DB_*, ANGEL_ONE_* (optional for paper mode)
PGPASSWORD=<yours> psql -h localhost -U postgres -d mcx_trading -f database/schema.sql

# 4. Resolve today's MCX option chain (real contracts, from Angel One's live instrument master)
.venv/bin/python -m data.angel_master_contract

# 5. Run
.venv/bin/python backend/app.py                     # http://localhost:5050
cd dashboard && npm install && npm run dev           # http://localhost:3000
```

Paper trading works immediately, no broker credentials required — the dashboard's Settings page has an Angel One credentials form for when you're ready to go live.

## Where things stand

Read **[CLAUDE.md](./CLAUDE.md)** — specifically "What's genuinely working vs. not yet wired" — before assuming any particular feature (live data feed, trained ML models, multi-underlying scanning, physical-settlement auto-exit) is production-ready. This is a research port, verified to boot and paper-trade correctly, not a finished trading system.

## License

MIT — see [LICENSE](./LICENSE).
