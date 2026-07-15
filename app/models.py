"""Core domain models used by Crypto Hunter AI."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class Coin:
    symbol: str
    base: str
    quote: str
    last_price: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    spread_percent: float = 0.0
    volume_24h: float = 0.0
    volatility_percent: float = 0.0
    active: bool = True


@dataclass(slots=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float = 0.0
    confirmed: bool = True


@dataclass(slots=True)
class OrderBook:
    bid_price: float
    ask_price: float
    bid_size: float
    ask_size: float

    @property
    def spread_percent(self) -> float:
        midpoint = (self.bid_price + self.ask_price) / 2
        if midpoint <= 0:
            return 0.0
        return ((self.ask_price - self.bid_price) / midpoint) * 100


@dataclass(slots=True)
class VolumeData:
    volume_15m: float = 0.0
    volume_1h: float = 0.0
    volume_4h: float = 0.0
    volume_24h: float = 0.0
    average_volume_7d: float = 0.0
    spike_percent: float = 0.0


@dataclass(slots=True)
class TechnicalData:
    rsi: float = 0.0
    ema9: float = 0.0
    ema21: float = 0.0
    ema50: float = 0.0
    ema200: float = 0.0
    macd: float = 0.0
    macd_signal: float = 0.0
    macd_histogram: float = 0.0
    atr: float = 0.0
    bollinger_upper: float = 0.0
    bollinger_middle: float = 0.0
    bollinger_lower: float = 0.0
    momentum: float = 0.0
    trend_strength: float = 0.0


@dataclass(slots=True)
class WatchCoin:
    coin: Coin
    volume: VolumeData = field(default_factory=VolumeData)
    technical: TechnicalData = field(default_factory=TechnicalData)
    score: float = 0.0
    rank: int = 0
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class Signal:
    symbol: str
    score: float
    action: str
    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    reasons: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class TradeRequest:
    symbol: str
    amount_try: float
    take_profit_percent: float
    stop_loss_percent: float
    confirmed: bool = False

    def validate(self) -> None:
        if not self.symbol.strip():
            raise ValueError("Coin sembolü boş olamaz.")
        if self.amount_try <= 0:
            raise ValueError("İşlem tutarı sıfırdan büyük olmalıdır.")
        if self.take_profit_percent <= 0:
            raise ValueError("Take-profit oranı sıfırdan büyük olmalıdır.")
        if self.stop_loss_percent <= 0:
            raise ValueError("Stop-loss oranı sıfırdan büyük olmalıdır.")
        if self.stop_loss_percent >= self.take_profit_percent:
            raise ValueError("Take-profit oranı stop-loss oranından büyük olmalıdır.")


@dataclass(slots=True)
class Position:
    symbol: str
    amount_try: float
    quantity: float
    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    opened_at: datetime = field(default_factory=utc_now)
    closed_at: Optional[datetime] = None
    exit_price: Optional[float] = None
    is_open: bool = True

    def close(self, exit_price: float) -> None:
        if exit_price <= 0:
            raise ValueError("Çıkış fiyatı sıfırdan büyük olmalıdır.")
        self.exit_price = exit_price
        self.closed_at = utc_now()
        self.is_open = False

    @property
    def profit_loss_percent(self) -> float:
        if self.exit_price is None or self.entry_price <= 0:
            return 0.0
        return ((self.exit_price - self.entry_price) / self.entry_price) * 100


@dataclass(slots=True)
class MarketFilterResult:
    accepted: bool
    symbol: str
    volume_score: float = 0.0
    volatility_score: float = 0.0
    liquidity_score: float = 0.0
    spread_score: float = 0.0
    total_score: float = 0.0
    rejection_reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WatchList:
    coins: list[WatchCoin] = field(default_factory=list)
    updated_at: Optional[datetime] = None

    def add(self, watch_coin: WatchCoin) -> None:
        existing = self.get(watch_coin.coin.symbol)
        if existing is None:
            self.coins.append(watch_coin)
        else:
            self.coins[self.coins.index(existing)] = watch_coin
        self.updated_at = utc_now()

    def remove(self, symbol: str) -> bool:
        existing = self.get(symbol)
        if existing is None:
            return False
        self.coins.remove(existing)
        self.updated_at = utc_now()
        return True

    def get(self, symbol: str) -> Optional[WatchCoin]:
        normalized = symbol.upper()
        return next(
            (item for item in self.coins if item.coin.symbol.upper() == normalized),
            None,
        )

    def sort_by_score(self) -> None:
        self.coins.sort(key=lambda item: item.score, reverse=True)
        for index, item in enumerate(self.coins, start=1):
            item.rank = index

    def top(self, count: int = 5) -> list[WatchCoin]:
        if count <= 0:
            return []
        self.sort_by_score()
        return self.coins[:count]

    def clear(self) -> None:
        self.coins.clear()
        self.updated_at = utc_now()

    def __len__(self) -> int:
        return len(self.coins)
