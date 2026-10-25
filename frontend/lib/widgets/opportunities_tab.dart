import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import 'owl_card.dart';

/// Dual Bot "Opportunities" tab: what the Smart Brain is watching right now (no signal yet, best first)
/// and its own pretend trades. Everything comes from the Smart Brain reply the screen already has. Paper only.
class OpportunitiesTab extends StatelessWidget {
  final Map<String, dynamic> brain;
  const OpportunitiesTab({super.key, required this.brain});

  static Map<String, dynamic> _map(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  static List<Map<String, dynamic>> _maps(dynamic v) =>
      v is List ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];
  static double _n(dynamic v) => v is num ? v.toDouble() : 0.0;
  static String _coin(dynamic s) => '$s'.replaceAll('USDT', '');
  static String _sg(num v) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}';

  Widget _watchRow(AppPalette p, BuildContext context, Map<String, dynamic> s) {
    final buy = _n(s['d']) > 0;
    final clean = _n(s['clean']);
    final prob = _map(s['prob']);
    final cc = clean >= 70 ? p.profit : (clean >= 40 ? p.warning : p.loss);
    final win = _n(prob['win_pct']);
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(12), border: Border.all(color: p.border)),
      child: IntrinsicHeight(
        child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Container(width: 4, color: cc),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Wrap(spacing: 6, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
                  Text(_coin(s['s']), style: context.type.primary.copyWith(fontWeight: FontWeight.w800)),
                  OwlChip(buy ? 'BUY' : 'SELL', buy ? p.profit : p.loss),
                  Text('${s['f'] ?? ''}', style: context.type.metadata),
                  OwlChip('Clean ${clean.toStringAsFixed(0)}', cc),
                  if (prob.isNotEmpty) OwlChip('${win.toStringAsFixed(0)}% won of ${_n(prob['n']).toStringAsFixed(0)}', win >= 55 ? p.profit : (win >= 45 ? p.warning : p.loss)),
                ]),
                if ('${s['verdict_text'] ?? ''}'.isNotEmpty)
                  Padding(padding: const EdgeInsets.only(top: 4), child: Text('${s['verdict_text']}', maxLines: 2, overflow: TextOverflow.ellipsis, style: context.type.metadata)),
              ]),
            ),
          ),
        ]),
      ),
    );
  }

  Widget _ownRow(AppPalette p, BuildContext context, Map<String, dynamic> t, {required bool open}) {
    final buy = _n(t['d']) > 0;
    final u = t['usdt'];
    final c = u is num ? (u >= 0 ? p.profit : p.loss) : p.textMuted;
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Row(children: [
        Icon(buy ? Icons.arrow_upward : Icons.arrow_downward, size: 15, color: buy ? p.profit : p.loss),
        const SizedBox(width: 6),
        Expanded(
          child: Text(
              open ? '${_coin(t['s'])} ${t['f'] ?? ''}${t['kind'] != null ? '  ·  ${t['kind']}' : ''}' : '${_coin(t['s'])}  ·  ${t['end'] ?? ''}',
              style: context.type.secondary.copyWith(fontWeight: FontWeight.w700)),
        ),
        Text(u is num ? '${_sg(u)} USDT' : 'just opened', style: context.type.secondary.copyWith(color: c, fontWeight: FontWeight.w700)),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    if (brain.isEmpty) {
      return OwlSectionCard(title: 'OPPORTUNITIES', children: [Text('Loading the Brain...', style: context.type.secondary)]);
    }
    final watch = _maps(brain['watch']);
    watch.sort((a, b) => _n(b['clean']).compareTo(_n(a['clean'])));
    final own = _map(brain['own']);
    final open = _maps(own['open']);
    final recent = _maps(own['recent']);
    final pnl = _n(own['pnl']);
    final n = _n(own['n']).toInt();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      OwlSectionCard(title: 'BRAIN IS WATCHING (BEST FIRST)', children: [
        Text('Coins that look like a good setup right now, even though no signal fired. A watch list only.', style: context.type.metadata),
        const SizedBox(height: 8),
        if (watch.isEmpty) Text('Nothing strong right now. The Brain scans again every 5 minutes.', style: context.type.secondary),
        for (final s in watch) _watchRow(p, context, s),
      ]),
      OwlSectionCard(
        title: "BRAIN'S OWN PAPER TRADES",
        edge: n == 0 ? p.textMuted : (pnl >= 0 ? p.profit : p.loss),
        children: [
          Text('${own['text'] ?? 'No own trade yet.'}', style: context.type.primary),
          if (open.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text('Open now', style: context.type.label.copyWith(fontWeight: FontWeight.w700)),
            for (final t in open) _ownRow(p, context, t, open: true),
          ],
          if (recent.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text('Last finished', style: context.type.label.copyWith(fontWeight: FontWeight.w700)),
            for (final t in recent) _ownRow(p, context, t, open: false),
          ],
          const SizedBox(height: 6),
          Text('Pretend money only. Dual Bot and the main bot are never touched.', style: context.type.metadata),
        ],
      ),
    ]);
  }
}
