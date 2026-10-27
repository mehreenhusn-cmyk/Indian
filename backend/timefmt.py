"""ONE place for time text (owner rule, 27 Oct 2026): under 1 min "45 s", under 1 h "12 min", 1 h or more "2 h 10 min"
(never "220 min"), 1 day or more "1 d 4 h". Same rules as fmtSpan() in frontend/lib/utils/format.dart. Never raises."""


def span(secs):
    try:
        s = int(round(float(secs)))
    except Exception:
        return "-"
    s = max(0, s)
    if s < 60:
        return "%d s" % s
    m = s // 60
    if m < 60:
        return "%d min" % m
    h, mm = divmod(m, 60)
    if h < 24:
        return "%d h" % h if mm == 0 else "%d h %d min" % (h, mm)
    d, hh = divmod(h, 24)
    return "%d d" % d if hh == 0 else "%d d %d h" % (d, hh)


def mins(m):
    """Same, but the input is minutes (number or None)."""
    try:
        return span(float(m) * 60.0)
    except Exception:
        return "-"
