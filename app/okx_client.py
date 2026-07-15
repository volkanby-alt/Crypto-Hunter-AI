"""Async OKX public market-data client.

This module intentionally uses only public endpoints. Trading and authenticated
account access will be implemented later behind a separate, safer adapter.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import config
from app.models import Candle, Coin, OrderBook


class OKXAPIError(RuntimeError):
    """Raised when OKX returns a non-success API response."""


class OKXTransportError(RuntimeError):
    """Raised when the HTTP request cannot be completed."""


class OKXPublicClient:
    """Small asynchronous client for OKX public spot-market endpoints."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int = 3,
    ) -> None:
        self.base_url = (base_url or config.okx_base_url).rstrip("/")
        self.timeout_seconds = timeout_seconds or config.request_timeout_seconds
        self.max_retries = max(1, max_retries)
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "OKXPublicClient":
        await self.open()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def open(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout_seconds),
                headers={
                    "Accept": "application/json",
                    "User-Agent": f"{config.app_name}/{config.version}",
                },
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get(
        self,
        path: str,
        params: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        await self.open()
        assert self._client is not None

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = await self._client.get(path, params=params)
                response.raise_for_status()
                payload = response.json()

                code = str(payload.get("code", ""))
                if code != "0":
                    raise OKXAPIError(
                        f"OKX API error {code}: {payload.get('msg', 'Unknown error')}"
                    )

                data = payload.get("data", [])
                if not isinstance(data, list):
                    raise OKXAPIError("OKX response data is not a list.")
                return data

            except OKXAPIError:
                raise
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    await asyncio.sleep(min(2 ** (attempt - 1), 4))

        raise OKXTransportError(
            f"OKX request failed after {self.max_retries} attempts: {last_error}"
        ) from last_error

    async def health_check(self) -> bool:
        try:
            data = await self._get(
                "/api/v5/public/time",
            )
            return bool(data and data[0].get("ts"))
        except (OKXAPIError, OKXTransportError):
            return False

    async def get_spot_instruments(self) -> list[dict[str, Any]]:
        return await self._get(
            "/api/v5/public/instruments",
            params={"instType": "SPOT"},
        )

    async def get_spot_tickers(self) -> list[dict[str, Any]]:
        return await self._get(
            "/api/v5/market/tickers",
            params={"instType": "SPOT"},
        )

    async def get_quote_tickers(
        self,
        quote_currency: str | None = None,
    ) -> list[dict[str, Any]]:
        quote = (quote_currency or config.quote_currency).upper()
        suffix = f"-{quote}"
        return [
            ticker
            for ticker in await self.get_spot_tickers()
            if str(ticker.get("instId", "")).upper().endswith(suffix)
        ]

    async def get_coin_universe(
        self,
        quote_currency: str | None = None,
    ) -> list[Coin]:
        quote = (quote_currency or config.quote_currency).upper()
        tickers = await self.get_quote_tickers(quote)
        coins: list[Coin] = []

        for ticker in tickers:
            symbol = str(ticker.get("instId", "")).upper()
            if not symbol or "-" not in symbol:
                continue

            base, parsed_quote = symbol.rsplit("-", 1)
            last = self._to_float(ticker.get("last"))
            bid = self._to_float(ticker.get("bidPx"))
            ask = self._to_float(ticker.get("askPx"))
            volume_24h = self._to_float(ticker.get("volCcy24h"))
            high_24h = self._to_float(ticker.get("high24h"))
            low_24h = self._to_float(ticker.get("low24h"))

            midpoint = (bid + ask) / 2 if bid > 0 and ask > 0 else 0.0
            spread = ((ask - bid) / midpoint) * 100 if midpoint > 0 else 0.0
            volatility = (
                ((high_24h - low_24h) / low_24h) * 100
                if low_24h > 0 and high_24h >= low_24h
                else 0.0
            )

            coins.append(
                Coin(
                    symbol=symbol,
                    base=base,
                    quote=parsed_quote,
                    last_price=last,
                    bid=bid,
                    ask=ask,
                    spread_percent=spread,
                    volume_24h=volume_24h,
                    volatility_percent=volatility,
                    active=last > 0,
                )
            )

        return coins

    async def get_candles(
        self,
        instrument: str,
        bar: str = "1H",
        limit: int = 200,
    ) -> list[Candle]:
        safe_limit = max(1, min(limit, 300))
        rows = await self._get(
            "/api/v5/market/candles",
            params={
                "instId": instrument.upper(),
                "bar": bar,
                "limit": str(safe_limit),
            },
        )

        candles: list[Candle] = []
        for row in reversed(rows):
            if not isinstance(row, list) or len(row) < 6:
                continue
            candles.append(
                Candle(
                    timestamp=datetime.fromtimestamp(
                        int(row[0]) / 1000,
                        tz=timezone.utc,
                    ),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                    quote_volume=float(row[7]) if len(row) > 7 else 0.0,
                    confirmed=(row[8] == "1") if len(row) > 8 else True,
                )
            )
        return candles

    async def get_order_book(
        self,
        instrument: str,
        depth: int = 5,
    ) -> OrderBook:
        safe_depth = max(1, min(depth, 400))
        data = await self._get(
            "/api/v5/market/books",
            params={
                "instId": instrument.upper(),
                "sz": str(safe_depth),
            },
        )
        if not data:
            raise OKXAPIError(f"No order-book data returned for {instrument}.")

        bids = data[0].get("bids") or []
        asks = data[0].get("asks") or []
        if not bids or not asks:
            raise OKXAPIError(f"Incomplete order book returned for {instrument}.")

        return OrderBook(
            bid_price=float(bids[0][0]),
            ask_price=float(asks[0][0]),
            bid_size=float(bids[0][1]),
            ask_size=float(asks[0][1]),
        )

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0
