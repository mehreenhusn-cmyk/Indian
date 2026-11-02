import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../theme/app_theme.dart';
import 'owl_card.dart';

/// Round 28 (Diagnostics, read-only): the DATA DOCTOR card. It says which coins have candle gaps and gives the exact Termux commands to run.
/// Reads only existing routes: GET /api/v2/gaps (the newest 200 gap records, kind = candle) and GET /api/v2/status (is the candle collector switch on). No new backend file.
/// Honest limit: gap records list the holes the collector KNEW about. A hole that was never logged is not shown here; the command `v2_candles_deep.py --plan` checks the store itself.
/// A gap with the reason "deep check" means the exchange has no candle for that slot (it is never asked again); other gaps can still be filled by the deep filler.
/// The commands are only text to copy. This card runs nothing, changes no switch and sends no order. Dart NOT compiled (the APK build is the proof).

const String kCmdSwitchOn = 'python3 backend/v2_candles.py --on';
const String kCmdPlan = 'python3 backend/v2_candles_deep.py --plan';
const String kCmdFill = 'python3 backend/v2_candles_deep.py --once';

class _Coin {
  final String symbol;
  int gaps = 0, final_ = 0;
  num newest = 0;
  final Set<String> frames = <String>{};
  _Coin(this.symbol);
}

String _two(int n) => n < 10 ? '0$n' : '$n';

String _utc(num t) {
  final d = DateTime.fromMillisecondsSinceEpoch(t.toInt() * 1000, isUtc: true);
  return '${_two(d.month)}-${_two(d.day)} ${_two(d.hour)}:${_two(d.minute)} UTC';
}

class DataDoctorCard extends StatelessWidget {
  final Map<String, dynamic>? gaps;
  final Map<String, dynamic>? status;
  const DataDoctorCard({super.key, required this.gaps, required this.status});

  bool _bad(Map<String, dynamic>? x) => x == null || x['state'] != null || x['error'] != null;

  List<_Coin> _coins() {
    final by = <String, _Coin>{};
    final rows = gaps?['rows'];
    if (rows is List) {
      for (final e in rows) {
        if (e is! Map || e['kind'] != 'candle') continue;
        final c = by.putIfAbsent('${e['symbol']}', () => _Coin('${e['symbol']}'));
        c.gaps++;
        if ('${e['reason']}'.contains('deep check')) c.final_++;
        c.frames.add('${e['interval']}');
        final t = e['to_ts'];
        if (t is num && t > c.newest) c.newest = t;
      }
    }
    final out = by.values.toList()..sort((a, b) => b.gaps.compareTo(a.gaps));
    return out;
  }

  Widget _cmd(BuildContext context, AppPalette p, String text, String note) => Padding(
        padding: const EdgeInsets.only(top: 6),
        child: Row(children: [
          Expanded(
            child: Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(color: p.bg, borderRadius: BorderRadius.circular(8)),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(text, style: TextStyle(fontSize: 11.5, fontFamily: 'monospace', color: p.textPrimary)),
                const SizedBox(height: 2),
                Text(note, style: TextStyle(fontSize: 10.5, color: p.textMuted)),
              ]),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.copy_rounded, size: 18),
            tooltip: 'Copy',
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: text));
              if (!context.mounted) return;
              ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Command copied. Paste it in Termux.')));
            },
          ),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    if (_bad(gaps)) {
      return OWLCard(
        edge: p.warning,
        child: Text('Data Doctor cannot read the candle gaps right now (the V2 API is off, old, or not reachable). Pull down to try again.',
            style: TextStyle(fontSize: 12.5, color: p.textPrimary)),
      );
    }
    final sw = status?['switches'];
    final on = sw is Map && sw['candles'] is bool ? sw['candles'] as bool : null;
    final coins = _coins();
    final total = coins.fold<int>(0, (a, c) => a + c.gaps);
    final col = coins.isEmpty ? p.profit : p.warning;
    final shown = coins.length > 8 ? coins.sublist(0, 8) : coins;
    return OWLCard(
      edge: col,
      padding: const EdgeInsets.all(12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Data Doctor', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary)),
        const SizedBox(height: 4),
        Text(
          coins.isEmpty
              ? 'No candle gaps are recorded in the newest 200 gap records.'
              : '${coins.length} coin(s) have candle gaps ($total records). Zone, Squeeze and Limits studies need about 35 to 37 hours of gap-free 5m candles, so a gap can leave a coin out.',
          style: TextStyle(fontSize: 12, color: p.textSecondary),
        ),
        const SizedBox(height: 6),
        for (final c in shown)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 2),
            child: Row(children: [
              Expanded(child: Text(c.symbol, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: p.textPrimary))),
              Flexible(
                child: Text('${c.gaps} gap(s) ${c.frames.join('/')}${c.final_ > 0 ? '  |  ${c.final_} no candle on exchange' : ''}  |  last ${c.newest == 0 ? 'n/a' : _utc(c.newest)}',
                    textAlign: TextAlign.right, style: TextStyle(fontSize: 10.5, color: p.textMuted)),
              ),
            ]),
          ),
        if (coins.length > shown.length)
          Text('+ ${coins.length - shown.length} more coins', style: TextStyle(fontSize: 11, color: p.textMuted)),
        const SizedBox(height: 8),
        Text(
          on == null
              ? 'Candle collector switch: not known.'
              : on
                  ? 'Candle collector switch: ON.'
                  : 'Candle collector switch: OFF. The deep filler does nothing until it is ON.',
          style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: on == false ? p.warning : p.textSecondary),
        ),
        if (on == false) _cmd(context, p, kCmdSwitchOn, '1. Switch the candle collector ON (one time).'),
        _cmd(context, p, kCmdPlan, '${on == false ? '2' : '1'}. Shows which coins have holes and how many slots (checks the store itself).'),
        _cmd(context, p, kCmdFill, '${on == false ? '3' : '2'}. Fills the holes with REAL candles from the exchange only (max 90 requests per run).'),
        const SizedBox(height: 6),
        Text('Copy a command and run it in Termux from the repo folder. This page runs nothing.', style: TextStyle(fontSize: 10.5, color: p.textMuted)),
      ]),
    );
  }
}
