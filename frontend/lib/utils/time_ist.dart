/// IST helpers (Round A, 26 Nov 2026). The backend writes times in UTC; the app SHOWS India time (IST = UTC + 5:30), so nothing on screen says "UTC".
/// The trading day itself still runs 5:30 AM IST to 5:30 AM IST (= 00:00 to 24:00 UTC): only the labels change, no number and no stored file.
const List<String> _mon = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

String _two(int n) => n < 10 ? '0$n' : '$n';

/// DateTime in UTC -> '26 Nov, 08:34'
String istFromDate(DateTime utc) {
  final d = utc.toUtc().add(const Duration(hours: 5, minutes: 30));
  return '${d.day} ${_mon[d.month - 1]}, ${_two(d.hour)}:${_two(d.minute)}';
}

/// Epoch seconds (or milliseconds) -> '26 Nov, 08:34'
String istFromEpoch(num t) {
  final ms = t > 1e11 ? t.toInt() : (t * 1000).toInt();
  return istFromDate(DateTime.fromMillisecondsSinceEpoch(ms, isUtc: true));
}

/// A backend text like '2026-11-26 03:04' or '2026-11-26T03:04:10Z' (UTC) -> '26 Nov, 08:34'. Anything it cannot read is returned as it came.
String istFromUtcText(Object? v) {
  final s = '${v ?? ''}'.trim();
  if (s.isEmpty || s == 'null') return '-';
  final d = DateTime.tryParse(s.contains('T') ? s : s.replaceFirst(' ', 'T'));
  if (d == null) return s;
  final utc = d.isUtc ? d : DateTime.utc(d.year, d.month, d.day, d.hour, d.minute, d.second); // a text without a zone is UTC
  return istFromDate(utc);
}
