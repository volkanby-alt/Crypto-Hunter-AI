"""Application configuration for Crypto Hunter AI."""

from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True, slots=True)
class Config:
    app_name: str = "Crypto Hunter AI"
    version: str = "0.2.0"
    debug: bool = True
    paper_mode: bool = True

    okx_base_url: str = "https://tr.okx.com"
    quote_currency: str = "USDT"
    request_timeout_seconds: float = 15.0
    max_concurrent_requests: int = 6

    scan_interval_seconds: int = 60
    watchlist_size: int = 75
    result_limit: int = 5

    min_volume_usdt: float = 5_000_000.0
    min_volatility_percent: float = 4.0
    max_spread_percent: float = 0.35
    min_liquidity_usdt: float = 500_000.0

    rsi_period: int = 14
    ema_fast: int = 9
    ema_medium: int = 21
    ema_slow: int = 50
    ema_long: int = 200
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    atr_period: int = 14
    bollinger_period: int = 20

    buy_score: float = 95.0
    strong_score: float = 90.0
    watch_score: float = 85.0

    default_buy_amount_try: float = 3_000.0
    default_stop_loss_percent: float = 3.0
    default_take_profit_percent: float = 7.0
    max_open_positions: int = 3

    enable_sound: bool = True
    enable_desktop_notification: bool = True

    data_dir: Path = BASE_DIR / "data"
    log_dir: Path = BASE_DIR / "logs"
    cache_dir: Path = BASE_DIR / "cache"


config = Config()
