"""Fetch prices and fundamentals for Bursa Malaysia stocks (Yahoo Finance, free)."""
import warnings

import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")


def ticker_for(code: str) -> str:
    return f"{code}.KL"


def fetch_prices(code: str, period: str = "3y") -> pd.DataFrame:
    df = yf.Ticker(ticker_for(code)).history(period=period, auto_adjust=False)
    if df.empty:
        raise RuntimeError(f"No price data for {code}")
    df.index = df.index.tz_localize(None)
    return df[["Open", "High", "Low", "Close", "Volume"]]


def fetch_fundamentals(code: str) -> dict:
    tk = yf.Ticker(ticker_for(code))
    info = tk.info or {}
    fund = {
        "name": info.get("longName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "summary": info.get("longBusinessSummary"),
        "market_cap": info.get("marketCap"),
        "pe": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "pb": info.get("priceToBook"),
        # yfinance 1.x already reports dividendYield as a percentage
        "dividend_yield": info.get("dividendYield"),
        "eps": info.get("trailingEps"),
        "roe": info.get("returnOnEquity"),
        "debt_to_equity": info.get("debtToEquity"),
        "profit_margin": info.get("profitMargins"),
        "website": info.get("website"),
        "annual": [],
    }
    try:
        inc = tk.income_stmt
        for col in list(inc.columns)[:5]:
            row = inc[col]
            fund["annual"].append({
                "year": str(col.year),
                "revenue": _num(row.get("Total Revenue")),
                "net_income": _num(row.get("Net Income")),
            })
    except Exception:
        pass
    return fund


def _num(v):
    try:
        return None if pd.isna(v) else float(v)
    except (TypeError, ValueError):
        return None
