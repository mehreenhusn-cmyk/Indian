import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import 'pd_widgets.dart';

/// "What the scanner learned" (26 Nov 2026). Closed by default: it asks the phone for the report only when opened (no background call).
/// Shows: how many alerts were checked and how many were real, which rule gave real ones, coins with a penalty / bonus, the threshold changes the tuner made.
class PdLearningCard extends StatefulWidget {
  const PdLearningCard({super.key});

  @override
  State<PdLearningCard> createState() => _PdLearningCardState();
}

class _PdLearningCardState extends State<PdLearningCard> {
  bool _open = false;
  bool _busy = false;
  Map<String, dynamic>? _d;

  Future<void> _load() async {
    if (_busy) return;
    setState(() => _busy = true);
    final d = await context.read<AppProvider>().fetchPdLearning();
    if (!mounted) return;
    setState(() {
      _d = d;
      _busy = false;
    });
  }

  void _toggle() {
    setState(() => _open = !_open);
    if (_open) _load();
  }

  String _rate(dynamic m) {
    if (m is! Map || m['n'] == null || pdNum(m['n']) == 0) return '-';
    return '${(pdNum(m['rate']) * 100).toStringAsFixed(0)}%  (${m['real']}/${m['n']})';
  }

  Widget _row(AppPalette p, String k, String v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(children: [
          Expanded(child: Text(k, style: TextStyle(fontSize: 12, color: p.textSecondary))),
          Text(v, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: p.textPrimary)),
        ]),
      );

  List<Widget> _body(AppPalette p) {
    final d = _d;
    if (d == null || _busy) return [const Padding(padding: EdgeInsets.all(14), child: Center(child: SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))))];
    if (d['state'] != null) return [Text('The learning report is not available yet.', style: TextStyle(fontSize: 12, color: p.textMuted))];
    final rep = d['report'] is Map ? d['report'] as Map : <dynamic, dynamic>{};
    final rules = rep['rules'] is Map ? rep['rules'] as Map : <dynamic, dynamic>{};
    final tot = rep['outcomes_14d'];
    final enough = rep['enough_data'] == true;
    final changes = d['changes'] is List ? d['changes'] as List : <dynamic>[];
    final pens = d['penalties'] is List ? d['penalties'] as List : <dynamic>[];
    final bons = d['bonuses'] is List ? d['bonuses'] as List : <dynamic>[];
    return [
      _row(p, 'Alerts checked (14 days)', tot is Map ? '${tot['n']}' : '0'),
      _row(p, 'Real alerts', _rate(tot)),
      if (!enough)
        Padding(
          padding: const EdgeInsets.only(top: 4, bottom: 4),
          child: Text('It needs about ${d['min_outcomes']} checked alerts before it changes any rule. Until then the first days can have more fake alerts.', style: TextStyle(fontSize: 11.5, color: p.warning)),
        ),
      const Divider(height: 18),
      Text('Which rule gave real moves', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: p.textPrimary)),
      const SizedBox(height: 4),
      _row(p, 'Pump alerts', _rate(rules['pump'])),
      _row(p, 'Dump alerts', _rate(rules['dump'])),
      _row(p, 'Broke its range', _rate(rules['breakout'])),
      _row(p, 'Did not break it', _rate(rules['no_breakout'])),
      _row(p, 'Flat before', _rate(rules['flat_before'])),
      _row(p, 'Volume 5-8x', _rate(rules['volume_5_to_8x'])),
      _row(p, 'Volume 8x+', _rate(rules['volume_8x_plus'])),
      const Divider(height: 18),
      _row(p, 'Start volume needed', '${pdNum(d['start_vol']).toStringAsFixed(1)}x  (default ${pdNum((d['defaults'] is Map ? d['defaults'] as Map : {})['start_vol']).toStringAsFixed(1)}x)'),
      _row(p, 'Missed moves (14 days)', '${rep['missed_14d'] ?? 0}'),
      if (pens.isNotEmpty) _row(p, 'Coins with a penalty', pens.map((e) => '${pdCoin('${(e as Map)['symbol']}')} ${pdNum(e['adj']).toStringAsFixed(0)}').join(', ')),
      if (bons.isNotEmpty) _row(p, 'Coins with a bonus', bons.map((e) => '${pdCoin('${(e as Map)['symbol']}')} +${pdNum(e['adj']).toStringAsFixed(0)}').join(', ')),
      if (changes.isNotEmpty) ...[
        const Divider(height: 18),
        Text('Changes the tuner made', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: p.textPrimary)),
        const SizedBox(height: 4),
        for (final c in changes.take(5)) Padding(padding: const EdgeInsets.symmetric(vertical: 2), child: Text('${(c as Map)['day']}: ${c['key']} ${c['old']} -> ${c['new']}. ${c['why']}', style: TextStyle(fontSize: 11.5, color: p.textSecondary))),
      ],
      const Divider(height: 18),
      Row(children: [
        Expanded(child: Text('Self-tuning of the rules', style: TextStyle(fontSize: 12.5, color: p.textPrimary))),
        Switch(
          value: d['auto_tune'] != false,
          onChanged: (v) async {
            await context.read<AppProvider>().setPdSwitch(autoTune: v);
            _load();
          },
        ),
      ]),
      Text('Off = only the daily report, no rule is changed.', style: TextStyle(fontSize: 11, color: p.textMuted)),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Container(
      decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), border: Border.all(color: p.border)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: _toggle,
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Row(children: [
              Icon(Icons.psychology_alt_outlined, size: 18, color: p.accent),
              const SizedBox(width: 8),
              Expanded(child: Text('What the scanner learned', style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w800, color: p.textPrimary))),
              Icon(_open ? Icons.expand_less_rounded : Icons.expand_more_rounded, color: p.textMuted),
            ]),
          ),
        ),
        if (_open) Padding(padding: const EdgeInsets.fromLTRB(12, 0, 12, 12), child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: _body(p))),
      ]),
    );
  }
}
