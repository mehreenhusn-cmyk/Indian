import 'dart:async';
import 'dart:ui' show FontFeature;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import 'owl_card.dart';

/// R24a: CURRENT BOT vs OWLSNIPER on the SAME days (Study Lab). Shows what GET /api/v2/sniper_h2h sends (backend owl_sniper_h2h.py).
/// Only days where BOTH closed a trade are compared. The fair number is % per trade (net USDT / money put in), because the Sniper trades tiny size.
/// The word (SNIPER AHEAD / CURRENT BOT AHEAD / TOO CLOSE / NOT ENOUGH DATA) comes ONLY from the backend: both sides need 30+ trades on 3+ shared days.
/// A hint, never a proof (different coins and moments). Folded by default (one line); asks once, then every 5 minutes while on screen. Read only, nothing trades.
/// Dart NOT compiled (the APK build is the proof).
class LabHeadToHeadCard extends StatefulWidget {
  const LabHeadToHeadCard({super.key});

  @override
  State<LabHeadToHeadCard> createState() => _LabHeadToHeadCardState();
}

class _LabHeadToHeadCardState extends State<LabHeadToHeadCard> {
  static const _tab = [FontFeature.tabularFigures()];
  Map<String, dynamic> _d = {};
  Timer? _timer;
  bool _busy = false;

  static double? _n(dynamic v) => v is num ? v.toDouble() : null;
  static Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  static String _s(double? v, [int dp = 2]) => v == null ? '--' : '${v >= 0 ? '+' : ''}${v.toStringAsFixed(dp)}';

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
      final d = await context.read<AppProvider>().fetchSniperH2H();
      if (mounted && d.isNotEmpty && d['state'] != null) setState(() => _d = d);
    } catch (_) {
      // keep the last good answer
    } finally {
      _busy = false;
    }
  }

  String _word(String v) {
    switch (v) {
      case 'SNIPER_AHEAD':
        return 'SNIPER AHEAD';
      case 'CURRENT_AHEAD':
        return 'CURRENT BOT AHEAD';
      case 'TOO_CLOSE':
        return 'TOO CLOSE';
      default:
        return 'NOT ENOUGH DATA';
    }
  }

  Widget _col(AppPalette p, String title, Map<String, dynamic> x) {
    final avg = _n(x['avg_pct']);
    final c = avg == null || avg == 0 ? p.textPrimary : (avg > 0 ? p.profit : p.loss);
    return Expanded(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: context.type.secondary.copyWith(fontWeight: FontWeight.w700)),
        const SizedBox(height: 4),
        Text('${_s(avg)}%', style: context.type.number.copyWith(color: c)),
        Text('per trade', style: context.type.metadata),
        const SizedBox(height: 6),
        Text('${_s(_n(x['net_usdt']))} USDT', style: context.type.secondary.copyWith(fontFeatures: _tab)),
        Text('${(_n(x['trades']) ?? 0).toInt()} trades, win ${_n(x['win_pct'])?.toStringAsFixed(0) ?? '--'}%', style: context.type.metadata),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final verdict = '${_d['verdict'] ?? 'NOT_ENOUGH_DATA'}';
    final ok = _d['state'] == 'OK';
    final shared = (_n(_d['shared_days']) ?? 0).toInt();
    final reasons = _d['reasons'] is List ? List<String>.from((_d['reasons'] as List).map((e) => '$e')) : <String>[];
    final head = _d.isEmpty ? 'Loading' : '${_word(verdict)}  ·  $shared shared days';
    final tone = !ok ? null : verdict == 'SNIPER_AHEAD' ? p.profit : verdict == 'CURRENT_AHEAD' ? p.warning : null;
    return OwlFold(
      title: 'CURRENT BOT vs SNIPER (SAME DAYS)',
      headline: head,
      headlineColor: tone,
      children: [
        Text('Only days where both closed a trade. % per trade = net USDT / money put in, so tiny Sniper size is fair. Paper trades, fees as booked. A hint, not a proof.', style: context.type.metadata),
        const SizedBox(height: 8),
        if (_d.isNotEmpty) Row(crossAxisAlignment: CrossAxisAlignment.start, children: [_col(p, 'Current Bot', _m(_d['current'])), const SizedBox(width: 12), _col(p, 'Sniper', _m(_d['sniper']))]),
        if (ok) ...[
          const SizedBox(height: 8),
          Text('Sniper won ${(_n(_d['sniper_day_wins']) ?? 0).toInt()} of $shared days, Current Bot ${(_n(_d['current_day_wins']) ?? 0).toInt()}. Gap ${_s(_n(_d['gap_pct']), 3)} points per trade.', style: context.type.secondary),
        ],
        for (final r in reasons) Padding(padding: const EdgeInsets.only(top: 6), child: Text(r, style: context.type.metadata)),
      ],
    );
  }
}
