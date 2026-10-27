/// Shared number formatting for prices, P&L and durations.
///
/// One place so Signals, Alerts and Positions always show the same
/// decimals for the same coin (a 0.08217 coin must never render as 0.08).

double? numOrNull(dynamic v) => v is num ? v.toDouble() : null;

/// Price with enough decimals for its magnitude.
String fmtPrice(double? v) {
  if (v == null) return '--';
  final a = v.abs();
  if (a >= 1000) return v.toStringAsFixed(2);
  if (a >= 100) return v.toStringAsFixed(3);
  if (a >= 10) return v.toStringAsFixed(4);
  if (a >= 1) return v.toStringAsFixed(4);
  if (a >= 0.1) return v.toStringAsFixed(5);
  if (a >= 0.01) return v.toStringAsFixed(5);
  if (a >= 0.001) return v.toStringAsFixed(6);
  return v.toStringAsFixed(7);
}

/// Signed number: +2.31 / -11.79.
String fmtSigned(double v, [int dp = 2]) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(dp)}';

/// Percent distance between two prices, relative to [from]. Always >= 0.
double? pctDist(double? from, double? to) {
  if (from == null || to == null || from == 0) return null;
  return ((to - from).abs() / from.abs()) * 100;
}

/// Reward:risk to a target. Risk = |entry - sl|, reward = |tp - entry|.
double? rrTo(double? entry, double? sl, double? tp) {
  if (entry == null || sl == null || tp == null) return null;
  final risk = (entry - sl).abs();
  if (risk == 0) return null;
  return (tp - entry).abs() / risk;
}

String fmtRR(double? rr) => rr == null ? '--' : '1:${rr.toStringAsFixed(1)}';

String fmtPctVal(double? p, [int dp = 2]) => p == null ? '--' : '${p.toStringAsFixed(dp)}%';

/// ONE place for time text (owner rule 27 Oct): under 1 min "45 s", under 1 h "12 min", 1 h or more "2 h 10 min"
/// (never "220 min"), 1 day or more "1 d 4 h". Use this everywhere a duration or age is shown.
String fmtSpan(num? secs, {bool withSeconds = false}) {
  if (secs == null || secs.isNaN || secs.isInfinite) return '--';
  final s = secs < 0 ? 0 : secs.round();
  if (s < 60) return '$s s';
  final m = s ~/ 60;
  if (m < 60) return withSeconds && s % 60 != 0 ? '$m min ${s % 60} s' : '$m min';
  final h = m ~/ 60;
  if (h < 24) return m % 60 == 0 ? '$h h' : '$h h ${m % 60} min';
  final d = h ~/ 24;
  return h % 24 == 0 ? '$d d' : '$d d ${h % 24} h';
}

/// Same, from minutes that may arrive as num or text (backend numbers).
String fmtMins(dynamic mins) {
  final v = mins is num ? mins : num.tryParse('${mins ?? ''}');
  return v == null ? '--' : fmtSpan(v * 60);
}

/// 1m 05s / 27m 30s / 2 h 05 min.
String fmtDuration(double? secs) {
  if (secs == null) return '--';
  final s = secs.round();
  if (s < 60) return '${s}s';
  final m = s ~/ 60;
  if (m < 60) return '${m}m ${(s % 60).toString().padLeft(2, '0')}s';
  return fmtSpan(s);
}

/// 1,000.00 style number with thousands separators.
String fmtMoney(double? v, [int dp = 2]) {
  if (v == null) return '--';
  final neg = v < 0;
  final parts = v.abs().toStringAsFixed(dp).split('.');
  final whole = parts[0].replaceAllMapped(RegExp(r'\B(?=(\d{3})+(?!\d))'), (m) => ',');
  final out = parts.length > 1 ? '$whole.${parts[1]}' : whole;
  return neg ? '-$out' : out;
}

/// Drop a trailing .0 : 100.0 -> 100, 2.5 -> 2.5
String fmtCompact(double v) => v % 1 == 0 ? v.toStringAsFixed(0) : v.toStringAsFixed(1);
