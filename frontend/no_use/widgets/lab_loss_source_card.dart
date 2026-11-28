import 'dart:async';
import 'dart:ui' show FontFeature;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import 'owl_card.dart';
import 'verdict_badge.dart';

/// R11: the ONE "Where is the money lost?" card of the Study Lab. Shows what GET /api/v2/lab_loss sends: the old replayed trades split into EXIT / SIDEWAYS / ENTRY / OTHER by what it cost in R (after fees),
/// the biggest leak as one line, and two checks (better exit? better entry?) judged on UNSEEN days by the booking / entry learners. The tags are hindsight, so the card never calls anything an edge by itself.
/// Read only, nothing trades. Folded by default (one line); asks once, then every 5 minutes while on screen (the numbers change every 6 hours).
class LabLossSourceCard extends StatefulWidget {
  const LabLossSourceCard({super.key});

  @override
  State<LabLossSourceCard> createState() => _LabLossSourceCardState();
}

class _LabLossSourceCardState extends State<LabLossSourceCard> {
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
      final d = await context.read<AppProvider>().fetchLabLoss();
      if (mounted && d.isNotEmpty) setState(() => _d = d);
    } catch (_) {
      // keep the last good answer
    } finally {
      _busy = false;
    }
  }

  Widget _bucket(AppPalette p, Map<String, dynamic> b) {
    final share = (_n(b['share_pct']) / 100).clamp(0.0, 1.0);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('${b['label']}', style: context.type.secondary.copyWith(fontWeight: FontWeight.w700))),
          Text('${_n(b['n']).toInt()} trades, ${_n(b['cost_r']).toStringAsFixed(1)} R, ${_n(b['share_pct']).toStringAsFixed(0)}%', style: context.type.secondary.copyWith(fontFeatures: _tab)),
        ]),
        const SizedBox(height: 3),
        ClipRRect(
          borderRadius: BorderRadius.circular(3),
          child: Stack(children: [
            Container(height: 6, color: p.border),
            FractionallySizedBox(widthFactor: share, child: Container(height: 6, color: p.loss)),
          ]),
        ),
        const SizedBox(height: 2),
        Text('${b['what'] ?? ''}', style: context.type.metadata),
      ]),
    );
  }

  Widget _fix(AppPalette p, String title, Map<String, dynamic> f) {
    if (f.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(title, style: context.type.secondary.copyWith(fontWeight: FontWeight.w700))),
          VerdictBadge(verdict: '${f['verdict'] ?? 'NOT_ENOUGH_DATA'}', compact: true),
        ]),
        const SizedBox(height: 2),
        Text('${f['headline'] ?? ''}', style: context.type.secondary),
        if ('${f['detail'] ?? ''}'.isNotEmpty) Text('${f['detail']}', style: context.type.metadata),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final state = '${_d['state'] ?? ''}';
    final buckets = _d['buckets'] is List ? List<Map<String, dynamic>>.from((_d['buckets'] as List).map(_m)) : <Map<String, dynamic>>[];
    final fix = _m(_d['fix']);
    final ok = state == 'OK' && buckets.isNotEmpty;
    final head = _d.isEmpty ? 'Loading' : '${_d['line'] ?? 'No answer yet'}';
    return OwlFold(
      title: 'WHERE IS THE MONEY LOST?',
      headline: head,
      headlineColor: ok ? p.warning : null,
      children: [
        Text('Old replayed trades (Dual / Brain / Main, last ${_n(_d['days']).toInt() == 0 ? 30 : _n(_d['days']).toInt()} days), 1R = the trade\'s own stop, after fees. Tags are hindsight: they show where the R went, not what to change.', style: context.type.metadata),
        const SizedBox(height: 6),
        if (ok) ...[
          for (final b in buckets) _bucket(p, b),
          Text('${_n(_d['n']).toInt()} trades, ${_n(_d['good']).toInt()} good, ${_n(_d['total_cost_r']).toStringAsFixed(1)} R cost in all.', style: context.type.metadata),
        ] else
          Text(_d.isEmpty ? 'Loading' : '${_n(_d['n']).toInt()} of ${_n(_d['need_n']).toInt() == 0 ? 30 : _n(_d['need_n']).toInt()} old trades with candles. The first run starts by itself a few minutes after the backend starts.', style: context.type.secondary),
        const SizedBox(height: 8),
        Text('IS THERE A FIX? (UNSEEN DAYS)', style: context.type.metadata),
        _fix(p, 'Better exit?', _m(fix['exit'])),
        _fix(p, 'Better entry?', _m(fix['entry'])),
      ],
    );
  }
}
