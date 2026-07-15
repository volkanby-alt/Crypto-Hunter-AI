"""Market filtering for high-volume and high-volatility spot coins.

The filter is intentionally deterministic and dependency-free. It ranks the
current OKX spot universe using relative market strength while still enforcing
hard safety thresholds for spread, liquidity and activity.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from app.config import config
from app.models import Coin, MarketFilterResult


@dataclass(frozen=True, slots=True)
class FilterThresholds:
    min_volume_usdt: float
    min_volatility_percent: float
    max_spread_percent: float
    min_liquidity_usdt: float


class MarketFilter:
    """Select and rank liquid, volatile USDT spot markets."""

    def __init__(
        self,
        thresholds: FilterThresholds | None = None,
        volume_percentile: float = 0.80,
        volatility_percentile: float = 0.55,
    ) -> None:
        self.thresholds = thresholds or FilterThresholds(
            min_volume_usdt=config.min_volume_usdt,
            min_volatility_percent=config.min_volatility_percent,
            max_spread_percent=config.max_spread_percent,
            min_liquidity_usdt=config.min_liquidity_usdt,
        )
        self.volume_percentile = self._clamp(volume_percentile, 0.0, 1.0)
        self.volatility_percentile = self._clamp(
            volatility_percentile,
            0.0,
            1.0,
        )

    def filter_universe(
        self,
        coins: list[Coin],
        limit: int | None = None,
    ) -> list[Coin]:
        """Return the strongest current candidates ordered by market score."""
        active = [coin for coin in coins if self._is_structurally_valid(coin)]
        if not active:
            return []

        dynamic_volume_floor = max(
            self.thresholds.min_volume_usdt,
            self._percentile(
                [coin.volume_24h for coin in active],
                self.volume_percentile,
            ),
        )
        dynamic_volatility_floor = max(
            self.thresholds.min_volatility_percent,
            self._percentile(
                [coin.volatility_percent for coin in active],
                self.volatility_percentile,
            ),
        )

        evaluated = [
            (
                coin,
                self.evaluate(
                    coin,
                    dynamic_volume_floor=dynamic_volume_floor,
                    dynamic_volatility_floor=dynamic_volatility_floor,
                ),
            )
            for coin in active
        ]

        accepted = [item for item in evaluated if item[1].accepted]
        accepted.sort(key=lambda item: item[1].total_score, reverse=True)

        safe_limit = max(1, limit or config.watchlist_size)
        return [coin for coin, _ in accepted[:safe_limit]]

    def evaluate(
        self,
        coin: Coin,
        *,
        dynamic_volume_floor: float | None = None,
        dynamic_volatility_floor: float | None = None,
    ) -> MarketFilterResult:
        """Evaluate one market and return detailed component scores."""
        reasons: list[str] = []

        volume_floor = max(
            self.thresholds.min_volume_usdt,
            dynamic_volume_floor or 0.0,
        )
        volatility_floor = max(
            self.thresholds.min_volatility_percent,
            dynamic_volatility_floor or 0.0,
        )

        if not coin.active or coin.last_price <= 0:
            reasons.append("Piyasa aktif değil veya fiyat geçersiz.")
        if coin.quote.upper() != config.quote_currency.upper():
            reasons.append("İşlem çifti hedef quote para biriminde değil.")
        if coin.volume_24h < volume_floor:
            reasons.append("24 saatlik hacim gerekli seviyenin altında.")
        if coin.volatility_percent < volatility_floor:
            reasons.append("24 saatlik volatilite gerekli seviyenin altında.")
        if coin.spread_percent < 0:
            reasons.append("Spread değeri geçersiz.")
        elif coin.spread_percent > self.thresholds.max_spread_percent:
            reasons.append("Alış-satış spread'i çok yüksek.")

        estimated_liquidity = self._estimated_liquidity(coin)
        if estimated_liquidity < self.thresholds.min_liquidity_usdt:
            reasons.append("Tahmini likidite güvenli seviyenin altında.")

        volume_score = self._ratio_score(coin.volume_24h, volume_floor)
        volatility_score = self._volatility_score(
            coin.volatility_percent,
            volatility_floor,
        )
        liquidity_score = self._ratio_score(
            estimated_liquidity,
            self.thresholds.min_liquidity_usdt,
        )
        spread_score = self._spread_score(coin.spread_percent)

        total_score = (
            volume_score * 0.40
            + volatility_score * 0.30
            + liquidity_score * 0.20
            + spread_score * 0.10
        )

        return MarketFilterResult(
            accepted=not reasons,
            symbol=coin.symbol,
            volume_score=round(volume_score, 2),
            volatility_score=round(volatility_score, 2),
            liquidity_score=round(liquidity_score, 2),
            spread_score=round(spread_score, 2),
            total_score=round(total_score, 2),
            rejection_reasons=reasons,
        )

    def rank_results(self, coins: list[Coin]) -> list[MarketFilterResult]:
        """Return diagnostics for all valid markets, best first."""
        active = [coin for coin in coins if self._is_structurally_valid(coin)]
        if not active:
            return []

        dynamic_volume_floor = max(
            self.thresholds.min_volume_usdt,
            self._percentile(
                [coin.volume_24h for coin in active],
                self.volume_percentile,
            ),
        )
        dynamic_volatility_floor = max(
            self.thresholds.min_volatility_percent,
            self._percentile(
                [coin.volatility_percent for coin in active],
                self.volatility_percentile,
            ),
        )

        results = [
            self.evaluate(
                coin,
                dynamic_volume_floor=dynamic_volume_floor,
                dynamic_volatility_floor=dynamic_volatility_floor,
            )
            for coin in active
        ]
        return sorted(results, key=lambda result: result.total_score, reverse=True)

    @staticmethod
    def _is_structurally_valid(coin: Coin) -> bool:
        return bool(
            coin.symbol
            and coin.base
            and coin.quote
            and coin.last_price > 0
            and coin.bid >= 0
            and coin.ask >= 0
            and coin.volume_24h >= 0
            and coin.volatility_percent >= 0
        )

    @staticmethod
    def _estimated_liquidity(coin: Coin) -> float:
        """Conservative liquidity proxy until depth aggregation is added."""
        if coin.spread_percent <= 0:
            return coin.volume_24h
        spread_penalty = max(0.10, 1.0 - (coin.spread_percent / 1.0))
        return coin.volume_24h * spread_penalty

    @staticmethod
    def _ratio_score(value: float, floor: float) -> float:
        if floor <= 0:
            return 0.0
        ratio = value / floor
        return MarketFilter._clamp(ratio * 50.0, 0.0, 100.0)

    @staticmethod
    def _volatility_score(value: float, floor: float) -> float:
        if floor <= 0:
            return 0.0
        ratio = value / floor
        base_score = ratio * 55.0
        if value > 25.0:
            base_score -= min((value - 25.0) * 1.5, 25.0)
        return MarketFilter._clamp(base_score, 0.0, 100.0)

    def _spread_score(self, spread_percent: float) -> float:
        maximum = self.thresholds.max_spread_percent
        if maximum <= 0 or spread_percent < 0:
            return 0.0
        if spread_percent >= maximum:
            return 0.0
        return (1.0 - (spread_percent / maximum)) * 100.0

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float:
        clean = sorted(value for value in values if value >= 0)
        if not clean:
            return 0.0
        if len(clean) == 1:
            return clean[0]

        position = (len(clean) - 1) * MarketFilter._clamp(
            percentile,
            0.0,
            1.0,
        )
        lower_index = int(position)
        upper_index = min(lower_index + 1, len(clean) - 1)
        fraction = position - lower_index
        return clean[lower_index] + (
            clean[upper_index] - clean[lower_index]
        ) * fraction

    @staticmethod
    def market_summary(coins: list[Coin]) -> dict[str, float]:
        """Small diagnostic snapshot for logs and future dashboard use."""
        if not coins:
            return {
                "count": 0.0,
                "median_volume_24h": 0.0,
                "median_volatility_percent": 0.0,
                "median_spread_percent": 0.0,
            }
        return {
            "count": float(len(coins)),
            "median_volume_24h": median(coin.volume_24h for coin in coins),
            "median_volatility_percent": median(
                coin.volatility_percent for coin in coins
            ),
            "median_spread_percent": median(
                coin.spread_percent for coin in coins
            ),
        }

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(value, maximum))
