import 'dart:async';
import 'dart:ui' show FontFeature;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';
import 'owl_card.dart';

/// R16b: the ONE "BTC Lab" card. BTC is the indicator TEST coin: its numbers are kept OUT of every Dual / Brain / Sniper / Dashboard total and live only here.
/// Shows what GET /api/v2/btc_lab sends: signals seen, finished, hit rate, USDT (margin 1000), 5m / 15m and the last 7 days. Read only, nothing trades.
/// Folded by default (one line); asks again every 60 seconds while it is on screen.
class BtcLabCard extends StatefulWidget {
  const BtcLabCard({super.key});

  @override
  State<BtcLabCard> createState() => _BtcLabCardState();
}

class _BtcLabCardState extends State<BtcLabCard> {
  static const _tab = [FontFeature.tabularFigures()];
  Map<String, dynamic> _d = {};
  Timer? _timer;
  bool _busy = false;

  static double _n(dynamic v) => v is num ? v.toDouble() : 0.0;
  static Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 60), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    if (_busy) return;
    _busy = true;
    try {
      final d = await context.read<AppProvider>().fetchBtcLab();
      if (mounted) setState(() => _d = d);
    } catch (_) {
      // keep the last good answer
    } finally {
      _busy = false;
    }
  }

  Widget _line(AppPalette p, String label, String value, [Color? c]) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(children: [
          Expanded(child: Text(label, style: context.type.secondary)),
          Text(value, style: context.type.secondary.copyWith(color: c ?? p.textPrimary, fontFeatures: _tab)),
        ]),
      );

  String _tfLine(Map<String, dynamic> t) {
    final n = _n(t['closed']).toInt();
    return n == 0 ? 'no finished trade' : '$n finished, ${fmtSigned(_n(t['net_usdt']))} USDT';
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final state = '${_d['state'] ?? ''}';
    final a = _m(_d['all']);
    final byTf = _m(a['by_tf']);
    final today = _m(_d['today']);
    final days = _d['days'] is List ? List<Map<String, dynamic>>.from((_d['days'] as List).map(_m)) : <Map<String, dynamic>>[];
    final seen = _n(a['seen']).toInt();
    final closed = _n(a['closed']).toInt();
    final net = _n(a['net_usdt']);
    final String head;
    if (state != 'ok') {
      head = state.isEmpty ? 'Loading' : 'No BTC data yet';
    } else {
      head = closed == 0 ? '$seen signals seen, none finished' : '$closed finished, ${a['hit_pct'] ?? '--'}% hit, ${fmtSigned(net)} USDT';
    }
    return OwlFold(
      title: 'BTC LAB (NOT IN ANY TOTAL)',
      headline: head,
      headlineColor: state == 'ok' && closed > 0 ? (net >= 0 ? p.profit : p.loss) : null,
      children: [
        Text('BTC is the indicator test coin. Its numbers stay here and are never added to Dual, Brain, Sniper or the Dashboard. USDT uses margin 1000.', style: context.type.metadata),
        const SizedBox(height: 6),
        _line(p, 'Signals seen (all days)', '$seen'),
        _line(p, 'Finished / still open', '$closed / ${_n(a['open']).toInt()}'),
        _line(p, 'Hit rate (profit trades)', a['hit_pct'] == null ? '--' : '${a['hit_pct']}%'),
        _line(p, 'Net, all days', '${fmtSigned(net)} USDT', closed == 0 ? null : (net >= 0 ? p.profit : p.loss)),
        _line(p, '5m', _tfLine(_m(byTf['5m']))),
        _line(p, '15m', _tfLine(_m(byTf['15m']))),
        _line(p, 'Today (closed)', _n(today['closed']) == 0 ? 'none yet' : '${_n(today['closed']).toInt()} finished, ${fmtSigned(_n(today['realized']))} USDT'),
        if (days.any((x) => _n(x['closed']) > 0)) ...[
          const SizedBox(height: 6),
          Text('LAST 7 DAYS (by the day the trade opened)', style: context.type.metadata),
          for (final x in days)
            if (_n(x['closed']) > 0) _line(p, '${x['day']}', '${_n(x['closed']).toInt()} trades, ${fmtSigned(_n(x['net_usdt']))} USDT', _n(x['net_usdt']) >= 0 ? p.profit : p.loss),
        ],
        if (_d['in_counts'] == true) ...[
          const SizedBox(height: 6),
          Text('Owner switch is ON (file ${_d['switch_file']}): BTC is counted in the totals again.', style: context.type.metadata.copyWith(color: p.warning)),
        ],
      ],
    );
  }
}
