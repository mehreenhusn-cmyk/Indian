import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import 'owl_card.dart';

/// Round 28 (Diagnostics, read-only): the OwlSniper health block, drawn from GET /api/v2/sniper_health (backend file api/health_v2.py, Round 23).
/// One headline (overall OK / WARN / BAD) and one tile per check (model, live scan, candles, switches, executor): a state dot, the label and the plain sentence the backend wrote.
/// State words come from the backend only: OK = green, WARN = amber, BAD = crimson, NOT_AVAILABLE = grey (the executor says so until it exists). Nothing is measured or guessed here.
/// Dart NOT compiled (the APK build is the proof).

List<Map<String, dynamic>> _list(Object? v) =>
    v is List ? [for (final e in v) if (e is Map) Map<String, dynamic>.from(e)] : <Map<String, dynamic>>[];

Color _col(AppPalette p, String s) => s == 'OK' ? p.profit : s == 'WARN' ? p.warning : s == 'BAD' ? p.loss : p.textMuted;

String _word(String s) => s == 'NOT_AVAILABLE' ? 'NOT AVAILABLE' : s;

class SniperHealthTiles extends StatelessWidget {
  /// The map from fetchSniperHealth(). A map with 'state' or 'error' (off / old / error) shows one plain problem card instead.
  final Map<String, dynamic>? r;
  const SniperHealthTiles({super.key, required this.r});

  String _problem(Map<String, dynamic> x) {
    if (x['error'] != null) return '${x['error']}';
    switch (x['state']) {
      case 'off':
        return 'The V2 data API is off. Make the file v2_api_enabled (containing 1) in the owl_data folder, then pull down.';
      case 'old':
        return 'This backend has no OwlSniper health route yet. Install the newest backend zip and restart it.';
      default:
        return 'Cannot read the OwlSniper health right now. Pull down to try again.';
    }
  }

  Widget _tile(AppPalette p, Map<String, dynamic> c) {
    final s = '${c['state'] ?? 'NOT_AVAILABLE'}';
    final col = _col(p, s);
    return OWLCard(
      padding: const EdgeInsets.all(10),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('${c['label'] ?? ''}', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary))),
          Icon(Icons.circle, size: 9, color: col),
        ]),
        const SizedBox(height: 2),
        Text(_word(s), style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: col)),
        const SizedBox(height: 4),
        Text('${c['text'] ?? ''}', style: TextStyle(fontSize: 11, color: p.textMuted)),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final x = r;
    if (x == null) return const SizedBox.shrink();
    if (x['state'] != null || x['error'] != null || x['checks'] == null) {
      return OWLCard(edge: p.warning, child: Text(_problem(x), style: TextStyle(fontSize: 12.5, color: p.textPrimary)));
    }
    final checks = _list(x['checks']);
    final overall = '${x['overall'] ?? 'WARN'}';
    final oc = _col(p, overall);
    final rows = <Widget>[];
    for (var i = 0; i < checks.length; i += 2) {
      rows.add(Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(child: _tile(p, checks[i])),
          const SizedBox(width: 8),
          Expanded(child: i + 1 < checks.length ? _tile(p, checks[i + 1]) : const SizedBox()),
        ]),
      ));
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      OWLCard(
        edge: oc,
        padding: const EdgeInsets.all(12),
        child: Row(children: [
          Icon(Icons.circle, size: 12, color: oc),
          const SizedBox(width: 10),
          Expanded(child: Text('OwlSniper: ${x['headline'] ?? ''}', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary))),
        ]),
      ),
      const SizedBox(height: 8),
      ...rows,
    ]);
  }
}
