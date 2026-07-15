"""Dynamic watchlist management for Crypto Hunter AI.

The manager builds a stable pool of high-volume and high-volatility coins.
Coins are not removed immediately after a single weak day; a small persistence
score protects consistently strong markets from short-lived volume drops.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.config import config
from app.market_filter import MarketFilter
from app.models import Coin, WatchCoin, WatchList


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class WatchlistMemory:
    symbol: str
    strength: float = 0.0
    consecutive_accepts: int = 0
    consecutive_rejects: int = 0
    last_seen_at: datetime = field(default_factory=utc_now)


class DynamicWatchlistManager:
    """Maintain a stable, ranked watchlist from the current market universe."""

    def __init__(
        self,
        market_filter: MarketFilter | None = None,
        size: int | None = None,
        removal_grace_cycles: int = 3,
    ) -> None:
        self.market_filter = market_filter or MarketFilter()
        self.size = max(1, size or config.watchlist_size)
        self.removal_grace_cycles = max(1, removal_grace_cycles)
        self.watchlist = WatchList()
        self._memory: dict[str, WatchlistMemory] = {}

    def update(self, universe: list[Coin]) -> WatchList:
        """Rebuild the watchlist while preserving short-term continuity."""
        ranked_results = self.market_filter.rank_results(universe)
        coin_map = {coin.symbol.upper(): coin for coin in universe}

        accepted_symbols = {
            result.symbol.upper()
            for result in ranked_results
            if result.accepted
        }

        self._update_memory(ranked_results)

        candidates: list[WatchCoin] = []
        for result in ranked_results:
            symbol = result.symbol.upper()
            coin = coin_map.get(symbol)
            if coin is None:
                continue

            memory = self._memory[symbol]
            keep_due_to_grace = (
                not result.accepted
                and memory.consecutive_rejects < self.removal_grace_cycles
                and self.watchlist.get(symbol) is not None
            )

            if not result.accepted and not keep_due_to_grace:
                continue

            persistence_bonus = min(memory.strength, 20.0)
            score = result.total_score + persistence_bonus

            candidates.append(
                WatchCoin(
                    coin=coin,
                    score=round(score, 2),
                    updated_at=utc_now(),
                )
            )

        candidates.sort(key=lambda item: item.score, reverse=True)
        selected = candidates[: self.size]

        new_watchlist = WatchList()
        for item in selected:
            new_watchlist.add(item)
        new_watchlist.sort_by_score()

        self.watchlist = new_watchlist
        self._decay_missing_symbols(accepted_symbols)
        return self.watchlist

    def top(self, count: int | None = None) -> list[WatchCoin]:
        return self.watchlist.top(count or config.result_limit)

    def symbols(self) -> list[str]:
        self.watchlist.sort_by_score()
        return [item.coin.symbol for item in self.watchlist.coins]

    def contains(self, symbol: str) -> bool:
        return self.watchlist.get(symbol) is not None

    def get(self, symbol: str) -> WatchCoin | None:
        return self.watchlist.get(symbol)

    def diagnostics(self) -> dict[str, object]:
        return {
            "count": len(self.watchlist),
            "symbols": self.symbols(),
            "updated_at": (
                self.watchlist.updated_at.isoformat()
                if self.watchlist.updated_at
                else None
            ),
        }

    def _update_memory(self, ranked_results: list) -> None:
        seen_symbols: set[str] = set()

        for result in ranked_results:
            symbol = result.symbol.upper()
            seen_symbols.add(symbol)
            memory = self._memory.setdefault(
                symbol,
                WatchlistMemory(symbol=symbol),
            )
            memory.last_seen_at = utc_now()

            if result.accepted:
                memory.consecutive_accepts += 1
                memory.consecutive_rejects = 0
                memory.strength = min(
                    20.0,
                    memory.strength + min(result.total_score / 100.0, 1.0) * 4.0,
                )
            else:
                memory.consecutive_rejects += 1
                memory.consecutive_accepts = 0
                memory.strength = max(0.0, memory.strength - 3.0)

        for symbol, memory in self._memory.items():
            if symbol not in seen_symbols:
                memory.consecutive_rejects += 1
                memory.consecutive_accepts = 0
                memory.strength = max(0.0, memory.strength - 4.0)

    def _decay_missing_symbols(self, accepted_symbols: set[str]) -> None:
        stale_symbols = [
            symbol
            for symbol, memory in self._memory.items()
            if symbol not in accepted_symbols
            and memory.consecutive_rejects >= self.removal_grace_cycles * 3
            and self.watchlist.get(symbol) is None
        ]
        for symbol in stale_symbols:
            self._memory.pop(symbol, None)
