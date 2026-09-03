import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_DIR = BASE_DIR / os.getenv("MODEL_DIR", "models/saved")
LOG_DIR = BASE_DIR / os.getenv("LOG_DIR", "logs")
MODEL_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ── Database (TimescaleDB) ─────────────────────────────────────────────────────
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "trading")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DB_URL = (
    f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    if DB_PASSWORD
    else f"postgresql://{DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# ── Angel One SmartAPI ─────────────────────────────────────────────────────────
ANGEL_ONE_API_KEY = os.getenv("ANGEL_ONE_API_KEY", "")
ANGEL_ONE_API_SECRET = os.getenv("ANGEL_ONE_API_SECRET", "")
ANGEL_ONE_ACCESS_TOKEN = os.getenv("ANGEL_ONE_ACCESS_TOKEN", "")
ANGEL_ONE_FEED_TOKEN = os.getenv("ANGEL_ONE_FEED_TOKEN", "")

# ── TrueData ──────────────────────────────────────────────────────────────────
TRUEDATA_USER = os.getenv("TRUEDATA_USER", "")
TRUEDATA_PASSWORD = os.getenv("TRUEDATA_PASSWORD", "")

# TrueData API Endpoints
TD_AUTH_URL = "https://auth.truedata.in/token"
TD_HISTORY_URL = "https://history.truedata.in"
TD_SYMBOL_MASTER_URL = "https://api.truedata.in"
TD_ANALYTICS_URL = "https://analytics.truedata.in"
TD_TCP_HOST = "push.truedata.in"
TD_TCP_PORT = int(os.getenv("TD_TCP_PORT", "8084"))

# TrueData rate limit (requests per second)
TD_RATE_LIMIT_RPS = 1

# ── Symbols (MCX commodities) ───────────────────────────────────────────────────
# CRUDEOIL / SILVER / GOLD options on MCX. Unlike the NIFTY app's single index,
# this project tracks three independent underlyings, each with its own strike
# gap, lot size, and expiry — all resolved live from Angel One's instrument
# master (data/angel_master_contract.py -> symbol_master table), never
# hardcoded. Run `python -m data.angel_master_contract` before first use.
SYMBOLS = ["CRUDEOIL", "SILVER", "GOLD"]

# The live dashboard scanner (backend/app.py) tracks ONE underlying at a
# time, same single-symbol architecture as the original NIFTY app — this
# is what it targets. Switch by changing this and restarting; true
# simultaneous multi-underlying scanning would need backend/app.py's
# scan_market()/tick-monitor loops generalized to iterate SYMBOLS, which
# hasn't been done (it's a real rewrite, not a config flip).
PRIMARY_UNDERLYING = os.getenv("MCX_PRIMARY_UNDERLYING", "CRUDEOIL")

# TrueData continuous-futures symbol mappings for MCX (used for live/historical
# price series to drive signal generation — VERIFY against TrueData's actual
# MCX symbol list before relying on this; MCX symbol conventions differ from
# NSE and weren't confirmed against a live TrueData account in this build).
TD_MCX_FUTURES_SYMBOLS = {
    "CRUDEOIL": "CRUDEOIL-I",
    "SILVER": "SILVER-I",
    "GOLD": "GOLD-I",
}
TD_INDEX_SYMBOLS = TD_MCX_FUTURES_SYMBOLS  # backwards-compat alias used by main.py ingest
# Older scripts inherited from the NIFTY app expect these two names too —
# MCX has no separate "spot index" the way NSE does, so both point at the
# same continuous-futures series. Those scripts have NOT been individually
# re-verified for MCX; this only prevents ImportError, not incorrect logic.
TD_INDEX_SPOT_SYMBOLS = TD_MCX_FUTURES_SYMBOLS
TD_INDEX_FUTURES_SYMBOLS = TD_MCX_FUTURES_SYMBOLS

# Symbols collected EOD-only via REST (no live websocket subscription).
EOD_ONLY_SYMBOLS: list[str] = []

# Fallback strike gaps ONLY for display/estimation before symbol_master is
# populated — real strike selection always uses the live listed strikes from
# symbol_master (backtest/mcx_option_resolver.get_available_strikes), because
# MCX revises these periodically. Do not trust these values for order sizing.
STRIKE_GAP = {
    "CRUDEOIL": 50,
    "SILVER": 100,
    "GOLD": 50,
}

# MCX commodity options expire monthly (date varies per commodity and per
# exchange revision) — always resolved from symbol_master, never hardcoded.
EXPIRY_CADENCE = {
    "CRUDEOIL": "monthly",
    "SILVER": "monthly",
    "GOLD": "monthly",
}

# MCX options are physically/deliverable settled — refuse new entries and
# force-close existing positions within this many days of expiry. See
# backtest/mcx_option_resolver.is_within_physical_settlement_window().
PHYSICAL_SETTLEMENT_CUTOFF_DAYS = int(os.getenv("PHYSICAL_SETTLEMENT_CUTOFF_DAYS", "3"))

# Number of strikes above/below ATM to track (±3 = 7 strikes per CE/PE)
ATM_RANGE = int(os.getenv("ATM_RANGE", "3"))

# Maximum symbols to subscribe (plan limit)
MAX_SYMBOLS = int(os.getenv("MAX_SYMBOLS", "50"))

# ── Trading Parameters ────────────────────────────────────────────────────────
INITIAL_CAPITAL = float(os.getenv("INITIAL_CAPITAL", "50000"))
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.01"))
MAX_TRADES_PER_DAY = int(os.getenv("MAX_TRADES_PER_DAY", "5"))
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", "0.05"))  # fraction of capital, e.g. 0.05 = 5%
SCORE_THRESHOLD = float(os.getenv("SCORE_THRESHOLD", "0.6"))

# ── Model Paths ───────────────────────────────────────────────────────────────
MACRO_MODEL_PATH = str(BASE_DIR / os.getenv("MACRO_MODEL_PATH", "models/saved/macro_model.pkl"))
MICRO_MODEL_PATH = str(BASE_DIR / os.getenv("MICRO_MODEL_PATH", "models/saved/micro_model.pkl"))

# ── Feature Configuration ─────────────────────────────────────────────────────
FEATURE_COLUMNS_MACRO = [
    # Price / Momentum (core)
    "rsi", "macd", "macd_signal", "macd_hist",
    "ema9", "ema20", "ema50", "sma200",
    "vwap_dist", "bollinger_upper", "bollinger_lower", "bollinger_width",
    "atr", "volume_ratio", "volume_sma20",
    # Momentum derivatives
    "stoch_rsi_k", "stoch_rsi_d", "williams_r",
    "roc_10", "roc_20", "adx", "di_plus", "di_minus", "cci",
    # Trend crossovers
    "ema9_20_cross", "ema20_50_cross", "close_above_sma200",
    # Trend context (added 2026-04-19)
    "close_vs_ema50_pct", "weekly_trend_slope", "pullback_in_uptrend",
    # Volatility
    "atr_pct", "bollinger_pct", "returns_1m",
    "volatility_20", "volatility_60", "vol_regime",
    # Candle patterns
    "candle_body_pct", "upper_shadow_pct", "lower_shadow_pct",
    # Multi-timeframe
    "rsi_5m", "rsi_15m", "ema20_5m", "atr_5m",
    # Session / time
    "minutes_since_open", "session_progress", "day_of_week",
    "is_first_hour", "is_last_hour",
    # Volume signals (expanded)
    "volume_change", "cum_volume_delta_20", "obv_slope", "mfi",
    # Options basics
    "oi_change", "pcr", "iv",
    # Options-aware (relative strike, expiry, cross-strike)
    "relative_strike", "days_to_expiry", "theta_pressure",
    "oi_skew", "pcr_near_atm", "pcr_far",
    "max_oi_call_rel", "max_oi_put_rel", "oi_concentration",
    "call_oi_gradient", "put_oi_gradient", "iv_skew",
]

FEATURE_COLUMNS_MICRO = [
    "bid_ask_spread", "order_imbalance", "trade_size_spike",
    "volume_burst", "tick_momentum",
]

# ── Trade Scoring Weights ─────────────────────────────────────────────────────
WEIGHT_ML_PROBABILITY = 0.50
WEIGHT_OPTIONS_FLOW = 0.30
WEIGHT_TECHNICAL_STRENGTH = 0.20
# WEIGHT_STRATEGY_PROB = 0.25  # reserved — strat_prob is used as gate only until models improve
STRAT_PROB_SCALE = 0.06             # normalize strat_prob raw output to [0,1] when needed

# ── Broker Execution ─────────────────────────────────────────────────────────
TRADE_MODE = os.getenv("TRADE_MODE", "paper")              # "paper" or "angelone"
ORDER_CONFIRMATION = os.getenv("ORDER_CONFIRMATION", "auto")  # "auto" or "manual"
MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS", "-5000"))
MAX_CONCURRENT_POSITIONS = int(os.getenv("MAX_CONCURRENT_POSITIONS", "1"))

# Angel One SmartAPI (only needed when TRADE_MODE=angelone)
ANGEL_ONE_CLIENT_ID = os.getenv("ANGEL_ONE_CLIENT_ID", "")
ANGEL_ONE_PASSWORD = os.getenv("ANGEL_ONE_PASSWORD", "")
ANGEL_ONE_TOTP_SECRET = os.getenv("ANGEL_ONE_TOTP_SECRET", "")

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ── Market Hours (IST) ───────────────────────────────────────────────────────
# MCX non-agri commodities (CRUDEOIL/SILVER/GOLD) trade 9:00 AM to 11:30 PM IST
# (11:55 PM during the US winter DST period) — far longer than NSE's 9:15-3:30.
# This session spans a UTC midnight rollover for anyone running the container
# in UTC, so date-boundary logic (e.g. "today's ticks") needs care.
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 0
MARKET_CLOSE_HOUR = 23
MARKET_CLOSE_MINUTE = 30

# ── Scan Cycle ────────────────────────────────────────────────────────────────
SCAN_INTERVAL_SECONDS = 60