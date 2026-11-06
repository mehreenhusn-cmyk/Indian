import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import 'owl_card.dart';

/// E4: "What did the Sniper learn from my winning trades, and can I trust it with 10 USDT?" in plain words.
/// Two read-only routes: GET /api/v2/sniper_winners (new: how winners differed from losers, from the past trades of the other bots) and
/// GET /api/v2/sniper_grad (the 7-check readiness list that already exists). Every sentence comes from the backend; this file only lays it out and
/// turns the checklist word into a plain answer. It never trades and never says "safe". Asks once, then every 5 minutes while on screen. Dart NOT compiled.
class SniperWinnersCard extends StatefulWidget {
  const SniperWinnersCard({super.key});

  @override
  State<SniperWinnersCard> createState() => _SniperWinnersCardState();
}

class _SniperWinnersCardState extends State<SniperWinnersCard> {
  Map<String, dynamic> _w = {};
  Map<String, dynamic> _g = {};
  Timer? _timer;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(minutes: 5), (_) => _load());
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
      final pr = context.read<AppProvider>();
      final w = await pr.fetchSniperWinners();
      final g = await pr.fetchSniperGrad();
      if (mounted) setState(() {
        if (w.isNotEmpty) _w = w;
        if (g.isNotEmpty && g['overall'] != null) _g = g;
      });
    } catch (_) {
      // keep the last good answers
    } finally {
      _busy = false;
    }
  }

  List<Map<String, dynamic>> _maps(Object? v) => v is List ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];

  String _answer(String overall, int passed, int total) {
    switch (overall) {
      case 'READY_TO_DISCUSS':
        return 'All $total checks passed. This is the point to think about real money. It is still your decision: start with a small amount you can afford to lose.';
      case 'NOT_YET':
        return 'Not yet. $passed of $total checks passed and at least one failed. Do not put real money in now.';
      default:
        return 'Not yet. Still collecting trades: $passed of $total checks passed. The rest wait for more data.';
    }
  }

  Widget _sectionTitle(String t) => Padding(
        padding: const EdgeInsets.only(top: AppSpacing.s, bottom: 4),
        child: Text(t, style: context.type.label.copyWith(fontWeight: FontWeight.w800)),
      );

  Widget _checkRow(AppPalette p, Map<String, dynamic> c) {
    final s = '${c['status']}';
    final col = s == 'PASS' ? p.profit : s == 'FAIL' ? p.loss : p.textSecondary;
    final word = s == 'PASS' ? 'OK' : s == 'FAIL' ? 'NO' : 'WAIT';
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox(width: 40, child: Text(word, style: context.type.metadata.copyWith(color: col, fontWeight: FontWeight.w800))),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${c['name'] ?? ''}', style: context.type.secondary.copyWith(fontWeight: FontWeight.w700)),
            if ('${c['text'] ?? ''}'.isNotEmpty) Text('${c['text']}', style: context.type.metadata),
          ]),
        ),
      ]),
    );
  }

  Widget _featureRow(AppPalette p, Map<String, dynamic> f) {
    final v = '${f['verdict']}';
    final col = v == 'NONE' ? p.textSecondary : p.profit;
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(v == 'NONE' ? '=  ' : '+  ', style: context.type.secondary.copyWith(color: col, fontWeight: FontWeight.w800)),
        Expanded(child: Text('${f['text'] ?? ''}', style: context.type.secondary)),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final overall = '${_g['overall'] ?? ''}';
    final checks = _maps(_g['checks']);
    final passed = _g['passed'] is num ? (_g['passed'] as num).toInt() : 0;
    final total = _g['total'] is num ? (_g['total'] as num).toInt() : checks.length;
    final state = '${_w['state'] ?? ''}';
    final n = _w['n'] is num ? (_w['n'] as num).toInt() : 0;
    final wins = _w['wins'] is num ? (_w['wins'] as num).toInt() : 0;
    final losses = _w['losses'] is num ? (_w['losses'] as num).toInt() : 0;
    final feats = _maps(_w['features']);
    final lines = _w['lines'] is List ? List<String>.from((_w['lines'] as List).map((e) => '$e')) : <String>[];
    final ready = overall == 'READY_TO_DISCUSS';
    final edge = ready ? p.profit : (overall == 'NOT_YET' ? p.loss : p.warning);
    return OWLCard(
      edge: edge,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Can I trust it with real money (for example 10 USDT)?', style: context.type.primary.copyWith(fontWeight: FontWeight.w800)),
        const SizedBox(height: 4),
        Text(_g.isEmpty ? 'Loading...' : _answer(overall, passed, total), style: context.type.secondary.copyWith(color: edge, fontWeight: FontWeight.w700)),
        for (final c in checks) _checkRow(p, c),
        _sectionTitle('What the Sniper learned from past trades'),
        if (_w.isEmpty)
          Text('Loading...', style: context.type.metadata)
        else if (state == 'off' || state == 'error' || state == 'old' || state == 'busy')
          Text(lines.isEmpty ? 'This is not available from the backend yet. Install the newest backend zip, restart it, then pull down.' : lines.first, style: context.type.metadata)
        else if (state == 'TOO_EARLY')
          Text(lines.isEmpty ? 'Too early to say.' : lines.first, style: context.type.secondary)
        else ...[
          Text('Studied $n past trades: $wins won, $losses lost.', style: context.type.secondary.copyWith(fontWeight: FontWeight.w700)),
          for (final f in feats) _featureRow(p, f),
        ],
        if (state == 'OK' && lines.length > 1) ...[
          const SizedBox(height: AppSpacing.s),
          Text(lines.last, style: context.type.caption),
        ],
        const SizedBox(height: AppSpacing.s),
        Text('How it learns faster: only more closed trades and more saved candles. Nothing here speeds that up by guessing. The checklist above is the honest test, and it never promises profit.', style: context.type.caption),
      ]),
    );
  }
}
