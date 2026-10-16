"""india_pricing.py - Black-Scholes option price, used ONLY by the replay/demo
data provider (no broker account needed). A live broker provider returns the real
premium instead, so paper results on this model are an approximation."""
import math


def _cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(spot, strike, t_years, iv, otype, r=0.065):
    intrinsic = max(spot - strike, 0.0) if otype == "CE" else max(strike - spot, 0.0)
    if t_years <= 0 or iv <= 0 or spot <= 0 or strike <= 0:
        return intrinsic
    sd = iv * math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t_years) / sd
    d2 = d1 - sd
    if otype == "CE":
        p = spot * _cdf(d1) - strike * math.exp(-r * t_years) * _cdf(d2)
    else:
        p = strike * math.exp(-r * t_years) * _cdf(-d2) - spot * _cdf(-d1)
    return max(p, intrinsic)
