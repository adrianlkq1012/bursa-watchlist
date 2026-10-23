"""Rule-based signals tuned for a mid-to-long-term investor.

Each rule adds or subtracts points and records a plain-English reason, so the
dashboard can show exactly why a stock got its rating. These are analytical
signals, not financial advice.
"""
import math

import pandas as pd


def _ok(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def trend_signals(df: pd.DataFrame) -> dict:
    last = df.iloc[-1]
    close, sma50, sma200 = last["Close"], last["SMA50"], last["SMA200"]
    score, reasons = 0.0, []

    if _ok(sma200):
        if close > sma200:
            score += 1
            reasons.append(("+", f"Price is above its 200-day average ({sma200:.3f}): long-term uptrend."))
        else:
            score -= 1
            reasons.append(("-", f"Price is below its 200-day average ({sma200:.3f}): long-term downtrend."))

        sma200_prev = df["SMA200"].iloc[-21]
        if _ok(sma200_prev):
            if sma200 > sma200_prev:
                score += 1
                reasons.append(("+", "The 200-day average is rising over the last month."))
            else:
                score -= 1
                reasons.append(("-", "The 200-day average is falling over the last month."))

    if _ok(sma50) and _ok(sma200):
        if sma50 > sma200:
            score += 1
            reasons.append(("+", "50-day average is above the 200-day (golden-cross structure)."))
        else:
            score -= 1
            reasons.append(("-", "50-day average is below the 200-day (death-cross structure)."))

    rsi = last["RSI14"]
    if _ok(rsi):
        if rsi > 70:
            score -= 0.5
            reasons.append(("-", f"RSI {rsi:.0f} is overbought: avoid chasing, wait for a pullback."))
        elif rsi < 30:
            score += 0.5
            reasons.append(("+", f"RSI {rsi:.0f} is oversold: possible bounce zone if fundamentals hold."))
        else:
            reasons.append(("=", f"RSI {rsi:.0f} is neutral."))

    if last["MACD_hist"] > 0:
        score += 0.5
        reasons.append(("+", "MACD is above its signal line: short-term momentum is positive."))
    else:
        score -= 0.5
        reasons.append(("-", "MACD is below its signal line: short-term momentum is negative."))

    return {"score": score, "reasons": reasons, "label": _label(score, 2)}


def valuation_signals(f: dict) -> dict:
    score, reasons = 0.0, []
    pe, pb, dy = f.get("pe"), f.get("pb"), f.get("dividend_yield")

    if not _ok(pe):
        score -= 1
        reasons.append(("-", "No trailing P/E: the company is loss-making over the last 12 months."))
    elif pe < 12:
        score += 1
        reasons.append(("+", f"P/E {pe:.1f} is low (cheap relative to earnings)."))
    elif pe > 25:
        score -= 1
        reasons.append(("-", f"P/E {pe:.1f} is high (market is pricing in a lot of growth)."))
    else:
        reasons.append(("=", f"P/E {pe:.1f} is moderate."))

    if _ok(pb):
        if pb < 1:
            score += 0.5
            reasons.append(("+", f"P/B {pb:.2f} is below 1: trading under book value."))
        elif pb > 3:
            score -= 0.5
            reasons.append(("-", f"P/B {pb:.2f} is rich versus book value."))
        else:
            reasons.append(("=", f"P/B {pb:.2f}."))

    if _ok(dy) and dy > 0:
        if dy >= 4:
            score += 1
            reasons.append(("+", f"Dividend yield {dy:.2f}% is attractive."))
        else:
            reasons.append(("=", f"Dividend yield {dy:.2f}%."))
    else:
        reasons.append(("=", "No dividend currently."))

    de = f.get("debt_to_equity")
    if _ok(de) and de > 150:
        score -= 0.5
        reasons.append(("-", f"Debt-to-equity {de:.0f}% is high."))

    return {"score": score, "reasons": reasons, "label": _label(score, 1)}


def overall(trend: dict, val: dict) -> str:
    total = trend["score"] + val["score"]
    if total >= 3:
        return "Bullish"
    if total <= -3:
        return "Bearish"
    return "Neutral"


def _label(score: float, threshold: float) -> str:
    if score >= threshold:
        return "Positive"
    if score <= -threshold:
        return "Negative"
    return "Mixed"
