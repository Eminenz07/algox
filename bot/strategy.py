"""
strategy.py
ALMA (Arnaud Legoux Moving Average) crossover signal detection.
Exactly matches Pine Script: ta.alma(src, 50, offset=2.0, sigma=5.0)
"""

import math
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── ALMA Implementation ───────────────────────────────────────────────────────

def compute_alma(series: pd.Series,
                 length: int   = 50,
                 offset: float = 2.0,
                 sigma:  float = 5.0) -> pd.Series:
    """
    Arnaud Legoux Moving Average.

    Matches Pine Script: ta.alma(src, length, offset, sigma)
    With offset=2.0, sigma=5.0 the gaussian center (m) sits BEYOND the window,
    so recent bars receive the highest relative weight — producing a fast,
    low-lag moving average similar to an aggressive EMA.

    Parameters
    ----------
    series : pd.Series   Source price series (close or open)
    length : int         Window size (default 50)
    offset : float       Gaussian centre as multiple of (length-1); 0=oldest bias, 1=newest bias
    sigma  : float       Controls the gaussian width (steepness of weighting)
    """
    m = math.floor(offset * (length - 1))   # gaussian center index
    s = length / sigma                       # gaussian standard deviation

    # Pre-compute normalised weight vector.
    # In pandas rolling, window[0]=oldest, window[-1]=newest.
    # In Pine Script, i=0=most recent → maps to window[length-1-i].
    # Result: weights[k] pairs with window[k] (oldest→newest).
    raw_w = np.array([math.exp(-((k - m) ** 2) / (2 * s ** 2)) for k in range(length)])
    w_sum = raw_w.sum()
    if w_sum == 0:
        return pd.Series(np.nan, index=series.index)
    weights = raw_w / w_sum

    return series.rolling(window=length, min_periods=length).apply(
        lambda window: float(np.dot(weights, window)), raw=True
    )


# ── Signal Detection ──────────────────────────────────────────────────────────

def detect_signal(df: pd.DataFrame,
                  length: int   = 50,
                  offset: float = 2.0,
                  sigma:  float = 5.0,
                  use_alternate_signals: bool = False,
                  alternate_signals_multiplier: int = 10,
                  timeframe: str = "15") -> str | None:
    """
    Run ALMA on close and open, check for crossover on the last confirmed bar.
    Optionally resamples the DataFrame to a higher timeframe for alternate signals.

    Parameters
    ----------
    df : pd.DataFrame  Must have columns: ['timestamp', 'open', 'close', 'high', 'low', 'volume']
                       Rows ordered oldest → newest.
                       The LAST row is the most recently CLOSED candle.
    """
    if use_alternate_signals:
        try:
            df_copy = df.copy()
            df_copy["datetime"] = pd.to_datetime(df_copy["timestamp"], unit="ms")
            df_copy.set_index("datetime", inplace=True)
            
            # Resample to multiplier * timeframe (in minutes)
            tf_minutes = int(timeframe)
            resample_tf = f"{tf_minutes * alternate_signals_multiplier}min"
            
            # Resample OHLCV
            resampled = df_copy.resample(resample_tf).agg({
                "timestamp": "first",
                "open":      "first",
                "high":      "max",
                "low":       "min",
                "close":     "last",
                "volume":    "sum",
            }).dropna().reset_index(drop=True)
            
            logger.debug("Resampled candles from %d to %d (Timeframe: %s)", 
                         len(df), len(resampled), resample_tf)
            df_to_use = resampled
        except Exception as exc:
            logger.error("Failed to resample candles for alternate signals: %s", exc)
            df_to_use = df
    else:
        df_to_use = df

    if len(df_to_use) < length + 1:
        logger.debug("Not enough bars (%d) for ALMA(%d) signal check", len(df_to_use), length)
        return None

    alma_close = compute_alma(df_to_use["close"], length, offset, sigma)
    alma_open  = compute_alma(df_to_use["open"],  length, offset, sigma)

    # Check the last two bars (index -1 = latest closed, -2 = previous)
    c0 = alma_close.iloc[-1];  o0 = alma_open.iloc[-1]
    c1 = alma_close.iloc[-2];  o1 = alma_open.iloc[-2]

    if pd.isna(c0) or pd.isna(o0) or pd.isna(c1) or pd.isna(o1):
        return None

    if c1 <= o1 and c0 > o0:   # crossed above → LONG
        logger.info("LONG signal detected (ALMA crossover)")
        return "LONG"
    if c1 >= o1 and c0 < o0:   # crossed below → SHORT
        logger.info("SHORT signal detected (ALMA crossunder)")
        return "SHORT"

    return None
