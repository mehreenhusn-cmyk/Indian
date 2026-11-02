"""owl_sniper_engine_a.py - OwlSniper ENGINE PART A of 3: the foundation maths (backend, plain python, NO numpy / pandas / sklearn / optuna).
Standalone: imports only `math`. It imports nothing from the bot, the Brain or Dual Bot. Nothing is traded, nothing is saved here.
Every function matches TradingView Pine v5 so the numbers on the chart and in the engine agree:
  sma(c, n)            = ta.sma
  ema(c, n)            = ta.ema   (seed = SMA of the first n real values, then alpha = 2 / (n + 1))
  pstdev(c, n)         = ta.stdev (POPULATION SD, divide by n; NOT the sample SD of pandas)
  zscore(c, n)         = (close - SMA) / SD
  tsi_matrix(c, 5, 25) = ta.tsi(close, 5, 25) * 100 = 100 * EMA(EMA(diff, 25), 5) / EMA(EMA(|diff|, 25), 5), signal = EMA(TSI, 14)
A value that cannot be computed yet (not enough candles, SD of zero for a Z-Score) is None, never a made-up number.
EXCLUDED on purpose: CHoCH and BOS (market structure). They are never computed, mapped or used here.
Part B (regime, features, signals) and Part C (simulator, split, search, OwlSniperEngine class) import from this file.
Run `python owl_sniper_engine_a.py` to run the built-in self-check (brute-force comparison, no test framework needed)."""
import math

VERSION = "owl_sniper_engine_a 1 (Part A)"
EXCLUDED = ("CHoCH", "BOS")
_REFRESH = 512            # the rolling SD re-anchors its sums every this many steps, so rounding drift can never build up


def _ok(x):
    """True for a real finite number (None, NaN and inf are not)."""
    return x is not None and x == x and x not in (math.inf, -math.inf)


def _check_len(n):
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise ValueError("length must be an integer >= 1, got %r" % (n,))


def first_valid(x):
    """Index of the first real number in a series, or None."""
    for i, v in enumerate(x):
        if _ok(v):
            return i
    return None


# ---------------------------------------------------------------- SMA
def sma(c, n):
    """Simple moving average of a clean series (no gaps). None until n values are there. Pine ta.sma.
    Running sum, rebuilt exactly every _REFRESH steps so rounding drift can never build up on long runs."""
    _check_len(n)
    out, run = [None] * len(c), 0.0
    for i in range(n - 1, len(c)):
        if (i - (n - 1)) % _REFRESH == 0:
            run = math.fsum(c[i - n + 1:i + 1])
        else:
            run += c[i] - c[i - n]
        out[i] = run / n
    return out


def sma_any(x, n):
    """SMA of a series with leading None values (the first n real values are needed). Pine does the same: na until n real bars."""
    _check_len(n)
    first = first_valid(x)
    if first is None:
        return [None] * len(x)
    return [None] * first + sma(x[first:], n)


# ---------------------------------------------------------------- EMA
def ema_any(x, n):
    """EMA that accepts leading None values. Seed = SMA of the first n real values (Pine ta.ema), then v = x*k + v*(1-k), k = 2/(n+1).
    A gap (None) after the start ends the series: the rest stays None (the caller must feed gap-free runs)."""
    _check_len(n)
    out = [None] * len(x)
    start = first_valid(x)
    if start is None or len(x) - start < n:
        return out
    seed = x[start:start + n]
    if not all(_ok(v) for v in seed):
        return out
    k = 2.0 / (n + 1)
    v = math.fsum(seed) / n
    out[start + n - 1] = v
    for i in range(start + n, len(x)):
        if not _ok(x[i]):
            break
        v = x[i] * k + v * (1.0 - k)
        out[i] = v
    return out


def ema(c, n):
    """EMA of a clean price series. Pine ta.ema."""
    return ema_any(c, n)


# ---------------------------------------------------------------- population standard deviation
def pstdev(c, n):
    """Rolling POPULATION standard deviation (divide by n) = Pine ta.stdev. None until n values are there.
    Fast O(len) rolling sums on values shifted by a reference price (keeps big prices exact); the sums are re-anchored
    every _REFRESH steps and after any jump beyond 10 SD, so the answer stays exact on very long runs and after huge price jumps."""
    _check_len(n)
    size = len(c)
    out = [None] * size
    if size < n:
        return out
    s1 = s2 = ref = 0.0
    for i in range(n - 1, size):
        jump = i > n - 1 and abs(c[i] - ref) > 10.0 * math.sqrt(max(s2 / n - (s1 / n) ** 2, 0.0)) + 1e-9
        if (i - (n - 1)) % _REFRESH == 0 or jump:   # fresh anchor (also after a price jump far outside the band, where old sums lose digits)
            win = c[i - n + 1:i + 1]
            ref = math.fsum(win) / n
            s1 = math.fsum(v - ref for v in win)
            s2 = math.fsum((v - ref) * (v - ref) for v in win)
        else:
            old, new = c[i - n] - ref, c[i] - ref
            s1 += new - old
            s2 += new * new - old * old
        m = s1 / n
        out[i] = math.sqrt(max(s2 / n - m * m, 0.0))
    return out


# ---------------------------------------------------------------- Z-Score and SD bands
def zscore(c, n, mean=None, sd=None):
    """Z = (close - SMA(n)) / SD(n). None while there is not enough data or when SD is 0 (flat market: no honest Z exists).
    Pass mean / sd if you already have them (saves a second loop)."""
    mean = mean if mean is not None else sma(c, n)
    sd = sd if sd is not None else pstdev(c, n)
    return [((c[i] - mean[i]) / sd[i]) if _ok(mean[i]) and _ok(sd[i]) and sd[i] > 0 else None for i in range(len(c))]


def sd_bands(mean, sd, k):
    """Price lines mean -+ k x SD (the +-1 / 2 / 3 SD bands of Special 13). Returns (upper, lower); None where mean or SD is None."""
    up = [(mean[i] + k * sd[i]) if _ok(mean[i]) and _ok(sd[i]) else None for i in range(len(mean))]
    lo = [(mean[i] - k * sd[i]) if _ok(mean[i]) and _ok(sd[i]) else None for i in range(len(mean))]
    return up, lo


# ---------------------------------------------------------------- TSI (double smoothed momentum)
def tsi_matrix(c, short=5, long=25, signal=14):
    """Pine: tsi = ta.tsi(close, short, long) * 100 = 100 * EMA(EMA(diff, long), short) / EMA(EMA(|diff|, long), short); signal = EMA(tsi, signal).
    Returns a dict of lists, all the same length as c, None where not computable yet:
      diff, adiff            1-candle price change and its absolute value (index 0 is None: there is no candle before it)
      num1, num2             first (long) and second (short) smoothing of diff
      den1, den2             first and second smoothing of |diff|
      tsi, signal, hist      -100..+100 line, its EMA, and tsi - signal
    A dead-flat market (den = 0) gives tsi = 0.0, the same as Pine's nz()."""
    n = len(c)
    diff = [None] + [c[i] - c[i - 1] for i in range(1, n)]
    adiff = [None] + [abs(c[i] - c[i - 1]) for i in range(1, n)]
    num1 = ema_any(diff, long)
    num2 = ema_any(num1, short)
    den1 = ema_any(adiff, long)
    den2 = ema_any(den1, short)
    tsi = [None] * n
    for i in range(n):
        if _ok(num2[i]) and _ok(den2[i]):
            tsi[i] = 100.0 * num2[i] / den2[i] if den2[i] > 0 else 0.0
    sig = ema_any(tsi, signal)
    hist = [(tsi[i] - sig[i]) if _ok(tsi[i]) and _ok(sig[i]) else None for i in range(n)]
    return {"diff": diff, "adiff": adiff, "num1": num1, "num2": num2, "den1": den1, "den2": den2,
            "tsi": tsi, "signal": sig, "hist": hist}


def tsi_series(c, short=5, long=25, signal=14):
    """Short form: (tsi, signal, hist) - the same tuple the old owl_sniper_engine.tsi_series returned."""
    m = tsi_matrix(c, short, long, signal)
    return m["tsi"], m["signal"], m["hist"]


# ---------------------------------------------------------------- self-check (no test framework needed)
def _brute_sma(c, n):
    return [None if i < n - 1 else sum(c[i - n + 1:i + 1]) / n for i in range(len(c))]


def _brute_pstdev(c, n):
    out = [None] * len(c)
    for i in range(n - 1, len(c)):
        w = c[i - n + 1:i + 1]
        m = sum(w) / n
        out[i] = math.sqrt(sum((v - m) ** 2 for v in w) / n)
    return out


def _brute_ema(c, n):
    out, k = [None] * len(c), 2.0 / (n + 1)
    if len(c) < n:
        return out
    v = sum(c[:n]) / n
    out[n - 1] = v
    for i in range(n, len(c)):
        v = c[i] * k + v * (1 - k)
        out[i] = v
    return out


def _same(a, b, tol=1e-9):
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if (x is None) != (y is None):
            return False
        if x is not None and abs(x - y) > tol * max(1.0, abs(y)):
            return False
    return True


def selftest():
    """Compares every function with a slow brute-force version on three price shapes. Returns a list of failures (empty = all good)."""
    import random
    rnd, bad = random.Random(7), []
    walk, v = [], 100.0
    for _ in range(1500):
        v *= 1.0 + rnd.gauss(0, 0.004)
        walk.append(v)
    shapes = {"walk": walk, "big_price": [60000.0 + x for x in walk], "jump": walk[:700] + [x * 40 for x in walk[700:]]}
    for name, c in shapes.items():
        for n in (1, 5, 20, 200):
            if not _same(sma(c, n), _brute_sma(c, n)):
                bad.append("sma %s n=%d" % (name, n))
            if not _same(ema(c, n), _brute_ema(c, n)):
                bad.append("ema %s n=%d" % (name, n))
            if not _same(pstdev(c, n), _brute_pstdev(c, n), 1e-7):
                bad.append("pstdev %s n=%d" % (name, n))
    flat = pstdev([5.0] * 30, 10)
    if flat[-1] != 0.0 or zscore([5.0] * 30, 10)[-1] is not None:
        bad.append("flat market: SD must be 0 and Z must be None")
    if pstdev([1.0, 2.0], 5) != [None, None]:
        bad.append("short series must give None")
    m = tsi_matrix(walk)
    vals = [x for x in m["tsi"] if x is not None]
    if not vals or min(vals) < -100 or max(vals) > 100:
        bad.append("tsi out of -100..100")
    if first_valid(m["tsi"]) != 1 + 25 - 1 + 5 - 1:          # diff starts at 1, EMA25 first value at 25, EMA5 of that at 29
        bad.append("tsi first valid index wrong: %r" % first_valid(m["tsi"]))
    if _ok(float("nan")) or not _ok(1.5):
        bad.append("_ok broken")
    return bad


if __name__ == "__main__":
    problems = selftest()
    print(VERSION, "SELF-CHECK:", "ALL GOOD" if not problems else "FAILED " + "; ".join(problems))
