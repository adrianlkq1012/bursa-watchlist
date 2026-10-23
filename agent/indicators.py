"""Technical indicators computed from daily OHLCV data."""
import pandas as pd


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    close = df["Close"]

    for n in (20, 50, 200):
        df[f"SMA{n}"] = close.rolling(n).mean()

    # RSI (Wilder's smoothing)
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    df["RSI14"] = 100 - 100 / (1 + gain / loss)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_hist"] = df["MACD"] - df["MACD_signal"]

    df["VOL20"] = df["Volume"].rolling(20).mean()
    return df


def key_levels(df: pd.DataFrame) -> dict:
    last_year = df.tail(252)
    last_3m = df.tail(63)
    return {
        "high_52w": float(last_year["High"].max()),
        "low_52w": float(last_year["Low"].min()),
        "support_3m": float(last_3m["Low"].min()),
        "resistance_3m": float(last_3m["High"].max()),
    }
