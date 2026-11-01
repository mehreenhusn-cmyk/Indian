import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';
import 'learning_progress_cards.dart';

/// Part E2: Exit Study screen, read-only, on the Part E1 route /api/v2/brain_exits.
/// The same closed trades are replayed with 4 exits: Current (stop / target / time), TSI turns against, half of the gain given back, break-even stop.
/// Per rule: net, give-back (open gain lost before the exit), worst dip, older half vs newer half, one verdict word (BETTER needs 60+ trades and a better net in BOTH halves).
/// Nothing is applied: BT-01 stays frozen, LIVE is locked. PAPER, SHADOW and REPLAY are separate tabs, never added. Dart NOT compiled (the APK build is the proof).
class ExitStudyScreen extends StatefulWidget {
  const ExitStudyScreen({super.key});

  @override
  State<ExitStudyScreen> createState() => _ExitStudyScreenState();
}

class _ExitStudyScreenState extends State<ExitStudyScreen> {
  Map<String, dynamic>? _r;
  bool _busy = true;
  String _src = 'REPLAY';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _busy = true);
    final r = await context.read<AppProvider>().fetchBrainExits(_src);
    if (!mounted) return;
    setState(() {
      _r = r;
      _busy = false;
    });
  }

  bool _bad(Map<String, dynamic>? r) => r == null || r['state'] != null || r['error'] != null || r['ready'] != true;

  String _problem(Map<String, dynamic>? r) {
    if (r != null && r['ready'] == false && r['note'] != null) return '${r['note']}';
    if (r != null && r['error'] != null) return '${r['error']}';
    switch (r == null ? 'error' : r['state']) {
      case 'off':
        return 'The V2 data API is off. Make the file v2_api_enabled (containing 1) in the owl_data folder, then pull down to refresh.';
      case 'old':
        return 'This backend does not have the exit study route yet. Install the newest zip, restart the backend, then pull down.';
      default:
        return 'Cannot reach the backend right now. Pull down to try again.';
    }
  }

  Widget _sources() => Wrap(spacing: 8, children: [
        for (final s in const ['REPLAY', 'PAPER', 'SHADOW'])
          ChoiceChip(
            label: Text(s),
            selected: _src == s,
            onSelected: (_) {
              if (_src == s) return;
              _src = s;
              _load();
            },
          ),
      ]);

  Color _word(AppPalette p, String w) => w == 'BETTER' ? p.profit : w == 'WORSE' ? p.loss : w == 'BASE' ? p.textSecondary : w == 'NOT ENOUGH DATA' ? p.textMuted : p.warning;

  Widget _kv(AppPalette p, String big, String label, [Color? c]) => Expanded(
        child: Column(children: [
          Text(big, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: c ?? p.textPrimary)),
          const SizedBox(height: 2),
          Text(label, textAlign: TextAlign.center, style: TextStyle(fontSize: 10.5, color: p.textMuted)),
        ]),
      );

  Widget _rule(AppPalette p, Map<String, dynamic> x) {
    final w = '${x['verdict'] ?? ''}';
    final c = _word(p, w);
    return OWLCard(
      edge: c,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('${x['name'] ?? ''}', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary))),
          Text(w, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: c)),
        ]),
        const SizedBox(height: 2),
        Text('${x['plain'] ?? ''}', style: TextStyle(fontSize: 11.5, color: p.textMuted)),
        const SizedBox(height: 10),
        Row(children: [
          _kv(p, lpSg(x['net_usdt']), 'Net USDT', lpNet(p, x['net_usdt'])),
          _kv(p, lpNum(x['giveback_usdt']).toStringAsFixed(2), 'Given back', p.warning),
          _kv(p, lpNum(x['worst_dip_usdt']).toStringAsFixed(2), 'Worst dip', p.loss),
          _kv(p, '${x['trades'] ?? 0}', 'Trades'),
        ]),
        const SizedBox(height: 10),
        Row(children: [
          _kv(p, lpSg(x['older_net']), 'Older half', lpNet(p, x['older_net'])),
          _kv(p, lpSg(x['newer_net']), 'Newer half', lpNet(p, x['newer_net'])),
        ]),
        const SizedBox(height: 10),
        Text('${x['text'] ?? ''}', style: TextStyle(fontSize: 12, color: p.textPrimary)),
      ]),
    );
  }

  Widget _top(AppPalette p, Map<String, dynamic> r) {
    final best = r['best'];
    final names = {for (final x in lpList(r['rules'])) '${x['key']}': '${x['name']}'};
    final text = best == null
        ? 'No exit rule is clearly better than the current exit yet. A rule needs 60+ trades and a better net in both halves.'
        : '${names['$best'] ?? best} is better than the current exit in both halves. This is a study only: nothing is applied.';
    return OWLCard(
      edge: best == null ? p.warning : p.profit,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Can the indicator close the trade better?', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary)),
        const SizedBox(height: 6),
        Text(text, style: TextStyle(fontSize: 12.5, color: p.textPrimary)),
        const SizedBox(height: 6),
        Text('${r['used'] ?? 0} trades used, ${r['skipped'] ?? 0} skipped (candles missing).', style: TextStyle(fontSize: 11.5, color: p.textSecondary)),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final r = _r;
    final List<Widget> kids;
    if (_busy && r == null) {
      kids = [const Padding(padding: EdgeInsets.all(40), child: Center(child: CircularProgressIndicator()))];
    } else if (_bad(r)) {
      kids = [_sources(), OWLCard(edge: p.warning, child: Text(_problem(r), style: TextStyle(fontSize: 13, color: p.textPrimary)))];
    } else {
      final ok = r!;
      kids = [
        _sources(),
        _top(p, ok),
        for (final x in lpList(ok['rules'])) _rule(p, x),
        Text('${ok['note'] ?? ''}', style: TextStyle(fontSize: 11, color: p.textMuted)),
      ];
    }
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(AppSpacing.l),
        children: [for (final k in kids) Padding(padding: const EdgeInsets.only(bottom: AppSpacing.m), child: k)],
      ),
    );
  }
}
