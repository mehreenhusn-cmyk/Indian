// Round 13: pure Dart, no import, no provider, no network. Used by widgets/dashboard_pairs.dart (and the Positions screen in Round 14).
/// Round 13 (pure function, no provider, no network): ONE row per symbol + side. The newest trade (largest opened_at_ts,
/// a tie keeps the later one in the list) is the row that is shown. The copy it returns also carries:
///   dup_count  how many raw rows were folded into it (1 = no duplicate)   dup_ids  the ids of ALL folded rows, newest first
/// so the screen can print "x2" instead of hiding the extra trade silently. Input maps are never changed.
/// Side: action BUY = LONG, anything else = SHORT. Rows that are not maps, or have no symbol, are skipped.
/// Output order: newest first.
List<Map<String, dynamic>> dedupePositions(List<dynamic> raw) {
  final best = <String, Map<String, dynamic>>{};
  final ids = <String, List<MapEntry<double, dynamic>>>{};
  for (final r in raw) {
    if (r is! Map) continue;
    final symbol = (r['symbol'] ?? '').toString();
    if (symbol.isEmpty) continue;
    final key = '$symbol|${r['action'] == 'BUY' ? 'LONG' : 'SHORT'}';
    final ts = (r['opened_at_ts'] is num) ? (r['opened_at_ts'] as num).toDouble() : 0.0;
    ids.putIfAbsent(key, () => []).add(MapEntry(ts, r['id']));
    final old = best[key];
    final oldTs = (old != null && old['opened_at_ts'] is num) ? (old['opened_at_ts'] as num).toDouble() : 0.0;
    if (old == null || ts >= oldTs) best[key] = Map<String, dynamic>.from(r);
  }
  final out = <Map<String, dynamic>>[];
  best.forEach((key, row) {
    final list = ids[key]!..sort((a, b) => b.key.compareTo(a.key));
    row['dup_count'] = list.length;
    row['dup_ids'] = [for (final e in list) e.value];
    out.add(row);
  });
  out.sort((a, b) {
    final x = (a['opened_at_ts'] is num) ? (a['opened_at_ts'] as num).toDouble() : 0.0;
    final y = (b['opened_at_ts'] is num) ? (b['opened_at_ts'] as num).toDouble() : 0.0;
    return y.compareTo(x);
  });
  return out;
}
