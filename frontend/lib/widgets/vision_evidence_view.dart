import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../theme/app_spacing.dart';
import 'owl_refresh.dart';

/// Evidence page: does the AI help the bot, and which indicator combinations really win or lose.
/// All numbers come from the backend (ai_evidence.py), after fees. The phone only draws them.
class VisionEvidenceView extends StatefulWidget {
  const VisionEvidenceView({super.key});

  @override
  State<VisionEvidenceView> createState() => _VisionEvidenceViewState();
}

class _VisionEvidenceViewState extends State<VisionEvidenceView> {
  Map<String, dynamic>? _data;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final r = await context.read<AppProvider>().fetchVisionEvidence();
    if (!mounted) return;
    setState(() {
      if (r != null) {
        _data = r;
        _failed = false;
      } else if (_data == null) {
        _failed = true;
      }
    });
  }

  Map<String, dynamic> _m(dynamic x) => x is Map ? Map<String, dynamic>.from(x) : <String, dynamic>{};
  List _l(dynamic x) => x is List ? x : const [];
  double _d(dynamic x) => x is num ? x.toDouble() : (double.tryParse('$x') ?? 0.0);

  Widget _card(AppPalette p, String title, List<Widget> kids, {Color? glow}) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: AppSpacing.cardGap),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium + 2),
        border: Border.all(color: glow != null ? glow.withOpacity(0.45) : p.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: context.type.metadata.copyWith(fontSize: 10, fontWeight: FontWeight.w700, letterSpacing: 0.7)),
          const SizedBox(height: 8),
          ...kids,
        ],
      ),
    );
  }

  Widget _tableRow(AppPalette p, Map<String, dynamic> r) {
    final n = _d(r['n']).toInt();
    final net = _d(r['net']);
    final c = net >= 0 ? p.profit : p.loss;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('${r['name'] ?? ''}', style: TextStyle(color: p.textPrimary, fontSize: 12.5, fontWeight: FontWeight.w700)),
                const SizedBox(height: 2),
                Text(n == 0 ? 'no finished trades yet' : '$n trades  ·  win ${r['win_rate']}%  ·  avg ${_d(r['avg']).toStringAsFixed(3)}',
                    style: context.type.metadata.copyWith(fontSize: 11)),
              ],
            ),
          ),
          Text(n == 0 ? '--' : '${net >= 0 ? '+' : ''}${net.toStringAsFixed(2)}', style: TextStyle(color: n == 0 ? p.textMuted : c, fontWeight: FontWeight.w800, fontSize: 14)),
        ],
      ),
    );
  }

  List<Widget> _patterns(AppPalette p, Map<String, dynamic> pt, String who) {
    final good = _l(pt['good']).map(_m).toList();
    final bad = _l(pt['bad']).map(_m).toList();
    final blocked = _m(pt['blocked_new']);
    final kids = <Widget>[
      Text('${pt['n'] ?? 0} tagged trades. ${pt['note'] ?? ''}', style: context.type.metadata.copyWith(height: 1.35)),
      const SizedBox(height: 8),
    ];
    Widget line(Map<String, dynamic> x, Color c) => Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('${x['pattern']}', style: TextStyle(color: p.textPrimary, fontSize: 12, fontWeight: FontWeight.w700, height: 1.3)),
              Text('older ${x['n_old']} trades avg ${_d(x['avg_old']).toStringAsFixed(2)}  ·  newer ${x['n_new']} trades avg ${_d(x['avg_new']).toStringAsFixed(2)}  ·  win ${x['win_rate']}%',
                  style: context.type.metadata.copyWith(fontSize: 10.5, color: c)),
            ],
          ),
        );
    if (good.isNotEmpty) {
      kids.add(Text('HOLDS ON NEW DATA - WINNING', style: context.type.metadata.copyWith(fontSize: 10, fontWeight: FontWeight.w700, color: p.profit)));
      kids.add(const SizedBox(height: 6));
      for (final x in good) {
        kids.add(line(x, p.profit));
      }
    }
    if (bad.isNotEmpty) {
      kids.add(Text('HOLDS ON NEW DATA - LOSING', style: context.type.metadata.copyWith(fontSize: 10, fontWeight: FontWeight.w700, color: p.loss)));
      kids.add(const SizedBox(height: 6));
      for (final x in bad) {
        kids.add(line(x, p.loss));
      }
      final bn = _d(blocked['n']).toInt();
      if (bn > 0) {
        final bnet = _d(blocked['net']);
        kids.add(Text(
            'Paper gate: on the newer trades, blocking these would have skipped $bn signals that made ${bnet >= 0 ? '+' : ''}${bnet.toStringAsFixed(2)} USDT. '
            '${bnet < 0 ? 'Blocking would have helped.' : 'Blocking would have cost profit.'}',
            style: context.type.metadata.copyWith(color: p.textPrimary, height: 1.35, fontSize: 12)));
      }
    }
    if (good.isEmpty && bad.isEmpty) {
      kids.add(Text('No combination is confirmed yet for $who.', style: context.type.metadata));
    }
    return kids;
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _data;
    if (d == null) {
      return Center(
        child: _failed
            ? Column(mainAxisSize: MainAxisSize.min, children: [
                Text('Could not load the evidence. It needs the newest backend.', style: context.type.metadata),
                TextButton(onPressed: _load, child: const Text('Retry')),
              ])
            : const CircularProgressIndicator(strokeWidth: 2),
      );
    }
    return OWLRefresh(
      onRefresh: _load,
      child: ListView(
        physics: owlPullPhysics,
        padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.s, AppSpacing.l, 96),
        children: [
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.s),
            child: Text('${d['note'] ?? ''} A pattern is only listed when it wins or loses on the older 60% AND the newer 40% of trades. Treat it as a hint until there are 100+ trades.',
                style: context.type.metadata.copyWith(height: 1.4)),
          ),
          _card(p, 'DOES THE AI HELP THE BOT?', [for (final r in _l(d['table'])) _tableRow(p, _m(r))], glow: p.accent),
          _card(p, 'BOT SIGNALS: WHICH COMBINATIONS WORK', _patterns(p, _m(d['bot_patterns']), 'bot signals')),
          _card(p, 'AI OWN: WHICH COMBINATIONS WORK', _patterns(p, _m(d['own_patterns']), 'AI Own')),
        ],
      ),
    );
  }
}
