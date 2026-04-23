"""
strategy.py — The file the research agent edits.

Current strategy: Baseline RSI with EMA trend filter.
- Long when RSI < oversold AND price above EMA (pullback in uptrend)
- Short when RSI > overbought AND price below EMA (pullback in downtrend)

The Strategy class must have:
  - __init__ accepting keyword params (for mutation by research.py)
  - on_candle(df) -> "LONG" | "SHORT" | "NOOP"
  - params() -> dict (for logging)

Keep logic simple. Research.py will generate many variants by mutating params.
"""

from __future__ import annotations

import pandas as pd


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = -delta.clip(upper=0).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-9)
    return 100 - 100 / (1 + rs)


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


class Strategy:
    def __init__(
        self,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        ema_period: int = 50,
    ):
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.ema_period = ema_period

    def params(self) -> dict:
        return {
            "name": "rsi_ema_baseline",
            "rsi_period": self.rsi_period,
            "rsi_oversold": self.rsi_oversold,
            "rsi_overbought": self.rsi_overbought,
            "ema_period": self.ema_period,
        }

    def on_candle(self, df: pd.DataFrame) -> str:
        """Return signal based on last closed candle.

        df must include at least `ema_period` rows. Returns one of:
        "LONG", "SHORT", "NOOP".
        """
        if len(df) < max(self.ema_period, self.rsi_period) + 2:
            return "NOOP"

        close = df["close"]
        r = rsi(close, self.rsi_period).iloc[-1]
        e = ema(close, self.ema_period).iloc[-1]
        price = close.iloc[-1]

        if r < self.rsi_oversold and price > e:
            return "LONG"
        if r > self.rsi_overbought and price < e:
            return "SHORT"
        return "NOOP"
