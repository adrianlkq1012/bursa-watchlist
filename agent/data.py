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


# Rows pulled from Yahoo's statements for the deep-dive tables
_INCOME = {"revenue": "Total Revenue", "gross_profit": "Gross Profit",
           "operating_income": "Operating Income", "net_income": "Net Income", "eps": "Diluted EPS"}
_BALANCE = {"total_assets": "Total Assets", "total_debt": "Total Debt",
            "cash": "Cash And Cash Equivalents", "equity": "Stockholders Equity"}
_CASHFLOW = {"operating_cf": "Operating Cash Flow", "capex": "Capital Expenditure",
             "free_cf": "Free Cash Flow", "dividends_paid": "Common Stock Dividend Paid"}


def _table(*frames_and_rows) -> dict:
    """Merge several statement DataFrames into {period: {field: value}}."""
    out = {}
    for df, rows in frames_and_rows:
        if df is None or df.empty:
            continue
        for col in df.columns:
            period = col.strftime("%Y-%m-%d")
            for field, row in rows.items():
                out.setdefault(period, {})[field] = _num(df.loc[row, col]) if row in df.index else None
    return dict(sorted(out.items(), reverse=True))


def fetch_financials(code: str) -> dict:
    tk = yf.Ticker(ticker_for(code))
    info = tk.info or {}
    fin = {"annual": {}, "quarterly": {}, "dividends_by_year": {}, "ownership": {}, "officers": [], "profile": {}}
    try:
        fin["annual"] = _table((tk.income_stmt, _INCOME), (tk.balance_sheet, _BALANCE), (tk.cashflow, _CASHFLOW))
        fin["quarterly"] = _table((tk.quarterly_income_stmt, _INCOME))
    except Exception as e:
        print(f"     statements failed for {code}: {e}")
    try:
        divs = tk.dividends
        fin["dividends_by_year"] = {str(y): round(float(v), 4) for y, v in divs.groupby(divs.index.year).sum().tail(8).items()}
    except Exception:
        pass
    for k in ("heldPercentInsiders", "heldPercentInstitutions"):
        fin["ownership"][k] = info.get(k)
    fin["officers"] = [{"name": o.get("name"), "title": o.get("title")} for o in info.get("companyOfficers", [])[:6]]
    fin["profile"] = {k: info.get(k) for k in (
        "sector", "industry", "fullTimeEmployees", "city", "country", "website", "sharesOutstanding",
        "totalCash", "totalDebt", "operatingCashflow", "freeCashflow", "grossMargins", "operatingMargins",
        "profitMargins", "returnOnEquity", "debtToEquity", "revenueGrowth", "currentRatio", "bookValue", "beta")}
    fin["summary"] = (info.get("longBusinessSummary") or "")[:1500]
    return fin
