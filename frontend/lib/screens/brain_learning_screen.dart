import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';

/// Part 88e adds a 5m / 15m switch and market-state tabs (Trend, Sideways, Consolidation, Breakout) to the Playbook tab, with the closed-trade count on each; the What-if tab always uses all trades.
/// Part 88d (What the Brain is learning): read-only. Two tabs on the Part 88c routes.
/// PLAYBOOK = /api/v2/brain_playbook: one block per indicator (EMA50 + SD bands, TSI, Z, histogram, TSI + Z, volume), the chart states that are USE / AVOID (30+ closed paper trades, same sign in both halves),
/// a holdout chip on each, the states still too thin and how many trades they need. WHAT-IF = /api/v2/brain_whatif: pick states by hand (Skip = drop trades that match, Only = keep trades that match),
/// see all trades (A) against what is left (B) on the SAME closed trades. Counterfactual only: nothing is saved, no rule changes, no order. Dart NOT compiled (the APK build is the proof).
class BrainLearningScreen extends StatefulWidget {
  const BrainLearningScreen({super.key});

  @override
  State<BrainLearningScreen> createState() => _BrainLearningScreenState();
}

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> _l(Object? v) => v is List ? [for (final e in v) _m(e)] : <Map<String, dynamic>>[];
List<String> _s(Object? v) => v is List ? [for (final e in v) '$e'] : <String>[];
String _f(Object? v) => v is num ? '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}' : '-';

class _Rule {
  final String mode; // skip or only
  final String dim;
  final String dimTitle;
  final String label;
  const _Rule(this.mode, this.dim, this.dimTitle, this.label);
}

class _BrainLearningScreenState extends State<BrainLearningScreen> {
  Map<String, dynamic>? _pb;
  Map<String, dynamic>? _wi;
  bool _busy = true;
  bool _running = false;
  String _mode = 'skip';
  String? _dim;
  String? _lab;
  final List<_Rule> _rules = [];
  String _ranKey = '';
  String _iv = '5m';
  String _sg = 'ALL';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _busy = true);
    final prov = context.read<AppProvider>();
    final pb = await prov.fetchBrainPlaybook(_iv, _sg);
    final wi = await prov.fetchBrainWhatif('', '');
    if (!mounted) return;
    setState(() {
      _pb = pb;
      _wi = wi;
      _busy = false;
    });
  }

  Future<void> _loadPb() async {
    final r = await context.read<AppProvider>().fetchBrainPlaybook(_iv, _sg);
    if (!mounted) return;
    setState(() => _pb = r);
  }

  Widget _filters(AppPalette p, Map<String, dynamic> r) {
    final ic = _m(r['interval_counts']);
    final sc = _m(r['state_counts']);
    const states = [
      ['ALL', 'All'],
      ['TREND', 'Trend'],
      ['SIDEWAYS', 'Sideways'],
      ['CONSOLIDATION', 'Consolidation'],
      ['BREAKOUT', 'Breakout'],
    ];
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, 'Timeframe and market state', 'Closed paper trades. Trend = up + down trend, Breakout = breakout + breakdown. The number is how many closed trades.'),
        Wrap(spacing: 8, children: [
          for (final t in ['5m', '15m'])
            ChoiceChip(
              label: Text('$t (${ic[t] ?? 0})'),
              selected: _iv == t,
              onSelected: (_) {
                setState(() => _iv = t);
                _loadPb();
              },
            ),
        ]),
        Wrap(spacing: 8, children: [
          for (final s in states)
            ChoiceChip(
              label: Text('${s[1]} (${sc[s[0]] ?? 0})'),
              selected: _sg == s[0],
              onSelected: (_) {
                setState(() => _sg = s[0]);
                _loadPb();
              },
            ),
        ]),
      ]),
    );
  }

  String _join(String mode) => _rules.where((r) => r.mode == mode).map((r) => '${r.dim}:${r.label}').join('|');

  Future<void> _run() async {
    setState(() => _running = true);
    final key = '${_join('skip')}#${_join('only')}';
    final r = await context.read<AppProvider>().fetchBrainWhatif(_join('skip'), _join('only'));
    if (!mounted) return;
    setState(() {
      _ranKey = key;
      _wi = r;
      _running = false;
    });
  }

  String _problem(Map<String, dynamic> r) {
    if (r['error'] != null) return '${r['error']}';
    switch (r['state']) {
      case 'off':
        return 'The V2 data API is off. Make the file v2_api_enabled (containing 1) in the owl_data folder, then pull down to refresh.';
      case 'old':
        return 'This backend does not have the Playbook routes yet. Install the newest zip, restart the backend, then pull down.';
      default:
        return 'Cannot reach the backend right now. Pull down to try again.';
    }
  }

  bool _bad(Map<String, dynamic>? r) => r == null || r['state'] != null || r['error'] != null || r['ready'] != true;

  Widget _msg(AppPalette p, Map<String, dynamic>? r) {
    final lines = r == null ? <String>[] : _s(r['lines']);
    final text = r != null && r['ready'] == false && lines.isNotEmpty ? lines.first : _problem(r ?? <String, dynamic>{'state': 'error'});
    return OWLCard(edge: p.warning, child: Text(text, style: TextStyle(fontSize: 13, color: p.textPrimary)));
  }

  Widget _title(AppPalette p, String t, [String? sub]) => Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(t, style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w800, color: p.textPrimary)),
          if (sub != null) Text(sub, style: TextStyle(fontSize: 11.5, color: p.textMuted)),
        ]),
      );

  Widget _chip(String t, Color c) => Container(
        margin: const EdgeInsets.only(right: 6, top: 4),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: c.withOpacity(0.14), borderRadius: BorderRadius.circular(8), border: Border.all(color: c.withOpacity(0.5))),
        child: Text(t, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: c)),
      );

  Widget _kv(AppPalette p, String k, String v, [Color? c]) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(children: [
          Expanded(child: Text(k, style: TextStyle(fontSize: 12.5, color: p.textSecondary))),
          Text(v, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: c ?? p.textPrimary)),
        ]),
      );

  Color _holdColor(AppPalette p, String s) => s == 'CONFIRMS' ? p.profit : (s == 'AGAINST' ? p.loss : p.warning);

  Widget _row(AppPalette p, Map<String, dynamic> r) {
    final use = r['verdict'] == 'USE';
    final c = use ? p.profit : p.loss;
    final h = _m(r['holdout']);
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${r['dim_title']}: ${r['label']}', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: p.textPrimary)),
        Text('${r['n']} trades, net ${_f(r['net_usdt'])} USDT (older half ${_f(r['older_net'])}, newer half ${_f(r['newer_net'])})', style: TextStyle(fontSize: 12, color: p.textSecondary)),
        Wrap(children: [
          _chip('${r['verdict']}', c),
          if (h.isNotEmpty) _chip('Holdout: ${h['status']} (${h['n']} of ${h['need']})', _holdColor(p, '${h['status']}')),
        ]),
      ]),
    );
  }

  Widget _block(AppPalette p, Map<String, dynamic> b) {
    final use = _l(b['use']);
    final avoid = _l(b['avoid']);
    final mixed = _l(b['mixed']);
    final near = _l(b['nearest']);
    final edge = use.isNotEmpty ? p.profit : (avoid.isNotEmpty ? p.loss : p.textMuted);
    final lines = _s(b['lines']);
    return OWLCard(
      edge: edge,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, '${b['title']}'),
        for (final r in [...use, ...avoid]) _row(p, r),
        if (use.isEmpty && avoid.isEmpty && lines.isNotEmpty) Text(lines.first, style: TextStyle(fontSize: 12.5, color: p.textSecondary)),
        if (mixed.isNotEmpty)
          Text('${mixed.length} state(s) have 30+ trades but the older and newer half disagree: MIXED, no verdict.', style: TextStyle(fontSize: 12, color: p.warning)),
        if (near.isNotEmpty) ...[
          const SizedBox(height: 4),
          Text('Closest to 30 trades (${b['thin_count']} states are still thin):', style: TextStyle(fontSize: 11.5, color: p.textMuted)),
          for (final n in near) Text('${n['label']}: ${n['n']} trades, needs ${n['needs']} more', style: TextStyle(fontSize: 11.5, color: p.textMuted)),
        ],
      ]),
    );
  }

  List<Widget> _playbook(AppPalette p) {
    final r = _pb;
    if (_bad(r)) return [_msg(p, r)];
    return [
      _filters(p, r!),
      OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(p, 'What the Brain is learning', 'Closed PAPER trades only, net of fee + slippage (pretend money)'),
          for (final s in _s(r['lines'])) Padding(padding: const EdgeInsets.only(bottom: 4), child: Text(s, style: TextStyle(fontSize: 12.5, color: p.textPrimary))),
        ]),
      ),
      for (final b in _l(r['blocks'])) _block(p, b),
      Text('${r['limit']}', style: TextStyle(fontSize: 11, color: p.textMuted)),
    ];
  }

  Widget _picker(AppPalette p, List<Map<String, dynamic>> ch) {
    final labs = _dim == null ? <Map<String, dynamic>>[] : _l(ch.firstWhere((c) => c['dim'] == _dim, orElse: () => <String, dynamic>{})['labels']);
    final full = _rules.length >= 4;
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, 'Pick states', 'Skip = drop trades that match ANY skip state. Only = keep trades that match ALL only states. At most 4 rules.'),
        Row(children: [
          ChoiceChip(label: const Text('Skip'), selected: _mode == 'skip', onSelected: (_) => setState(() => _mode = 'skip')),
          const SizedBox(width: 8),
          ChoiceChip(label: const Text('Only'), selected: _mode == 'only', onSelected: (_) => setState(() => _mode = 'only')),
        ]),
        DropdownButton<String>(
          isExpanded: true,
          hint: const Text('Indicator group'),
          value: _dim,
          items: [for (final c in ch) DropdownMenuItem<String>(value: '${c['dim']}', child: Text('${c['title']}'))],
          onChanged: (v) => setState(() {
            _dim = v;
            _lab = null;
          }),
        ),
        DropdownButton<String>(
          isExpanded: true,
          hint: const Text('State'),
          value: _lab,
          items: [for (final l in labs) DropdownMenuItem<String>(value: '${l['label']}', child: Text('${l['label']} (${l['n']} trades)', overflow: TextOverflow.ellipsis))],
          onChanged: (v) => setState(() => _lab = v),
        ),
        Row(children: [
          ElevatedButton(
            onPressed: full || _dim == null || _lab == null
                ? null
                : () => setState(() {
                      final t = '${ch.firstWhere((c) => c['dim'] == _dim)['title']}';
                      _rules.add(_Rule(_mode, _dim!, t, _lab!));
                      _lab = null;
                    }),
            child: const Text('Add rule'),
          ),
          const SizedBox(width: 8),
          ElevatedButton(onPressed: _rules.isEmpty || _running ? null : _run, child: Text(_running ? 'Working...' : 'Run what-if')),
        ]),
        Wrap(children: [
          for (var i = 0; i < _rules.length; i++)
            Padding(
              padding: const EdgeInsets.only(right: 6, top: 4),
              child: Chip(
                label: Text('${_rules[i].mode == 'skip' ? 'Skip' : 'Only'}: ${_rules[i].dimTitle} = ${_rules[i].label}', style: const TextStyle(fontSize: 11)),
                onDeleted: () => setState(() => _rules.removeAt(i)),
              ),
            ),
        ]),
      ]),
    );
  }

  Widget _result(AppPalette p, Map<String, dynamic> r) {
    final x = _m(r['result']);
    final a = _m(x['A']);
    final b = _m(x['B']);
    final d = _m(x['dropped']);
    final h = _m(d['holdout']);
    final st = '${x['status']}';
    final good = st.startsWith('LOOKS BETTER');
    return OWLCard(
      edge: good ? p.accent : p.warning,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, 'What-if result', 'Same closed trades, counterfactual: nothing runs'),
        Wrap(children: [_chip(st, good ? p.accent : p.warning)]),
        const SizedBox(height: 6),
        _kv(p, 'A: all trades', '${a['n']} trades, ${_f(a['net_usdt'])} USDT'),
        _kv(p, 'B: what is left', '${b['n']} trades, ${_f(b['net_usdt'])} USDT', good ? p.profit : null),
        _kv(p, 'Dropped trades', '${d['n']} trades, ${_f(d['net_usdt'])} USDT'),
        _kv(p, 'Today A / B', '${_f(x['today_A_net'])} / ${_f(x['today_B_net'])} USDT'),
        if (h.isNotEmpty) _kv(p, 'Holdout of dropped', '${h['status']} (${h['n']} newest)', _holdColor(p, '${h['status']}')),
        const SizedBox(height: 4),
        for (final s in _s(r['lines'])) Padding(padding: const EdgeInsets.only(bottom: 3), child: Text(s, style: TextStyle(fontSize: 11.5, color: p.textMuted))),
      ]),
    );
  }

  List<Widget> _whatif(AppPalette p) {
    final r = _wi;
    if (_bad(r)) return [_msg(p, r)];
    final ch = _l(r!['choices']);
    return [
      _picker(p, ch),
      if (_rules.isNotEmpty && _ranKey == '${_join('skip')}#${_join('only')}' && _m(r['result']).isNotEmpty) _result(p, r),
      Text('${r['limit']}', style: TextStyle(fontSize: 11, color: p.textMuted)),
    ];
  }

  Widget _tab(AppPalette p, List<Widget> kids) => RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(AppSpacing.l),
          children: [for (final k in kids) Padding(padding: const EdgeInsets.only(bottom: AppSpacing.m), child: k)],
        ),
      );

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final loading = [const Padding(padding: EdgeInsets.all(40), child: Center(child: CircularProgressIndicator()))];
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(title: const Text('What the Brain is learning'), bottom: const TabBar(tabs: [Tab(text: 'Playbook'), Tab(text: 'What-if')])),
        body: TabBarView(children: [
          _tab(p, _busy && _pb == null ? loading : _playbook(p)),
          _tab(p, _busy && _wi == null ? loading : _whatif(p)),
        ]),
      ),
    );
  }
}
