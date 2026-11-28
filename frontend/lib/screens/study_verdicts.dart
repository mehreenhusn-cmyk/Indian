import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/load_state.dart';
import '../widgets/owl_card.dart';

/// Part 39 (FILE 47): STUDY VERDICTS. One plain line per old backtest / study finding: what was tested, what it found, and does Sniper use it (YES / TESTING / NO).
/// Read only: it asks GET /api/v2/sniper_prior (Part 38) and shows what the backend says; nothing is worked out here and nothing is opened, closed or changed.
/// Layout (Study Lab rule): the summary on top (verdict counts + how many Sniper uses / tests / does not use), then the list (best verdicts first), then the raw parts collapsed (re-tests, exit / management notes, which source worked).
/// YES = Sniper re-tested it on its own fresh candles and confirmed it. TESTING = Sniper is still collecting cases (n of 30) or it holds only sometimes. NO = refuted, or not an entry finding / no matching Sniper test: the reason is on the row.
/// Replay studies never show EDGE (best word HINT). Below the minimum cases a finding says NOT ENOUGH DATA, never a fake number. LoadSpinner (Part 1): 12 s then Retry.
/// Use: StudyVerdicts(). Dart NOT compiled (the APK build is the proof).

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> _l(Object? v) => v is List ? [for (final e in v) _m(e)] : <Map<String, dynamic>>[];
double _d(Object? v) => v is num ? v.toDouble() : 0.0;

const _order = ['EDGE', 'HINT', 'AVOID', 'LOSING', 'NO_EDGE', 'DIAGNOSIS_ONLY', 'NOT_ENOUGH_DATA'];
const _showFirst = 12;

class StudyVerdicts extends StatefulWidget {
  final String tf;
  final int freshDays;
  const StudyVerdicts({super.key, this.tf = '5m', this.freshDays = 30});

  @override
  State<StudyVerdicts> createState() => _StudyVerdictsState();
}

class _StudyVerdictsState extends State<StudyVerdicts> {
  Map<String, dynamic>? _data;
  bool _busy = true;
  String _filter = 'ALL';
  bool _all = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _busy = true);
    final d = await context.read<AppProvider>().fetchSniperPrior(tf: widget.tf, freshDays: widget.freshDays);
    if (!mounted) return;
    setState(() {
      _data = d;
      _busy = false;
    });
  }

  String _word(String v) => v.replaceAll('_', ' ');

  Color _vc(AppPalette p, String v) {
    switch (v) {
      case 'EDGE':
        return p.profit;
      case 'HINT':
        return p.accent;
      case 'AVOID':
        return p.warning;
      case 'LOSING':
        return p.loss;
      case 'DIAGNOSIS_ONLY':
        return p.textSecondary;
      default:
        return p.textMuted;
    }
  }

  Color _uc(AppPalette p, String u) => u == 'YES' ? p.profit : (u == 'TESTING' ? p.warning : p.textMuted);

  Widget _chip(String text, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: c.withOpacity(0.15), borderRadius: BorderRadius.circular(20)),
        child: Text(text, style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w800, color: c)),
      );

  Widget _title(AppPalette p) => Text('What was tested (old studies)', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary));

  Widget _line(AppPalette p, String t, {Color? c, double size = 12}) =>
      Padding(padding: const EdgeInsets.only(top: 5), child: Text(t, style: TextStyle(fontSize: size, color: c ?? p.textSecondary)));

  Widget _note(AppPalette p, String text, {Color? edge, String? chip, bool retry = false}) => OWLCard(
        edge: edge,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [Expanded(child: _title(p)), if (chip != null) _chip(chip, edge ?? p.textMuted)]),
          _line(p, text, c: p.textPrimary),
          if (retry) Align(alignment: Alignment.centerLeft, child: TextButton(onPressed: _load, child: const Text('Retry'))),
        ]),
      );

  Widget _row(AppPalette p, Map<String, dynamic> r) {
    final v = '${r['verdict']}', u = '${r['used_by_sniper']}';
    final n = _d(r['n']).toInt();
    final date = r['date'] == null ? '' : ' · ${r['date']}';
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          _chip(_word(v), _vc(p, v)),
          const SizedBox(width: 6),
          Expanded(child: Text('${r['what']}', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: p.textPrimary), maxLines: 2, overflow: TextOverflow.ellipsis)),
          const SizedBox(width: 6),
          _chip('Sniper: $u', _uc(p, u)),
        ]),
        _line(p, '${r['line']}', size: 11.5),
        _line(p, '$n cases$date · ${r['why']}', size: 10.5, c: p.textMuted),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _data;
    if (_busy || d == null) return OWLCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [_title(p), LoadSpinner(onRetry: _load)]));
    final st = '${d['state']}';
    if (st == 'off') return _note(p, 'The V2 data API or the Sniper is switched off, so the study list cannot be read.', edge: p.textMuted, chip: 'OFF');
    if (st == 'old') return _note(p, 'This backend has no study list route yet. Install the newest backend zip and restart the backend.', edge: p.warning, chip: 'OLD BACKEND');
    if (st == 'busy') return _note(p, '${d['text'] ?? 'The study list is being built. Try again in a minute.'}', edge: p.warning, chip: 'BUSY', retry: true);
    if (st == 'error') return _note(p, '${d['text'] ?? 'The study list could not be read.'}', edge: p.loss, chip: 'ERROR', retry: true);
    final counts = _m(d['counts']);
    final used = _m(d['used_counts']);
    final rows = _l(d['rows']);
    final sorted = [...rows]..sort((a, b) {
        final c = _order.indexOf('${a['verdict']}').compareTo(_order.indexOf('${b['verdict']}'));
        return c != 0 ? c : '${a['used_by_sniper']}'.compareTo('${b['used_by_sniper']}') * -1;
      });
    final list = _filter == 'ALL' ? sorted : [for (final r in sorted) if ('${r['used_by_sniper']}' == _filter) r];
    final shown = _all || list.length <= _showFirst ? list : list.sublist(0, _showFirst);
    final sources = _m(d['sources']);
    final bad = [for (final e in sources.entries) if ('${_m(e.value)['state']}' != 'ok') '${e.key}: ${_m(e.value)['state']} ${_m(e.value)['note'] ?? ''}'];
    final cands = _l(d['cands']);
    final notes = _l(d['notes']);
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [Expanded(child: _title(p)), _chip('${rows.length} findings', p.textMuted)]),
        const SizedBox(height: 8),
        Text('Sniper uses ${_d(used['YES']).toInt()}, is testing ${_d(used['TESTING']).toInt()}, does not use ${_d(used['NO']).toInt()}.', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
        _line(p, 'Old findings are only a start: Sniper re-tests each one on fresh candles (last ${d['fresh_days']} days) before it trusts it.', size: 11.5),
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Wrap(spacing: 6, runSpacing: 6, children: [
            for (final v in _order) if (_d(counts[v]) > 0) _chip('${_word(v)} ${_d(counts[v]).toInt()}', _vc(p, v)),
          ]),
        ),
        Padding(
          padding: const EdgeInsets.only(top: 10),
          child: Wrap(spacing: 8, children: [
            for (final f in const ['ALL', 'YES', 'TESTING', 'NO'])
              ChoiceChip(
                label: Text(f == 'ALL' ? 'All' : (f == 'YES' ? 'Used' : (f == 'TESTING' ? 'Testing' : 'Not used')), style: const TextStyle(fontSize: 12)),
                selected: _filter == f,
                onSelected: (_) => setState(() {
                  _filter = f;
                  _all = false;
                }),
              ),
          ]),
        ),
        if (list.isEmpty) _line(p, 'Nothing in this group yet.', c: p.textMuted),
        for (final r in shown) _row(p, r),
        if (list.length > shown.length) TextButton(onPressed: () => setState(() => _all = true), child: Text('Show all ${list.length}')),
        const Divider(height: 22),
        Theme(
          data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
          child: Column(children: [
            if (cands.isNotEmpty)
              ExpansionTile(
                tilePadding: EdgeInsets.zero,
                childrenPadding: EdgeInsets.zero,
                title: Text('Sniper re-tests (${cands.length})', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: p.textSecondary)),
                expandedCrossAxisAlignment: CrossAxisAlignment.start,
                children: [for (final c in cands) _line(p, '${c['status']}: ${c['plain']}', size: 11.5)],
              ),
            if (notes.isNotEmpty)
              ExpansionTile(
                tilePadding: EdgeInsets.zero,
                childrenPadding: EdgeInsets.zero,
                title: Text('Exit and trade-management notes (${notes.length})', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: p.textSecondary)),
                expandedCrossAxisAlignment: CrossAxisAlignment.start,
                children: [for (final n in notes) _line(p, '${_word('${n['verdict']}')}: ${n['line']}', size: 11.5)],
              ),
            ExpansionTile(
              tilePadding: EdgeInsets.zero,
              childrenPadding: EdgeInsets.zero,
              title: Text('Sources (${sources.length})', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: p.textSecondary)),
              expandedCrossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (bad.isEmpty) _line(p, 'All sources answered.', size: 11.5) else for (final b in bad) _line(p, b, size: 11.5, c: p.warning),
                _line(p, 'Exit, level and wait studies are replays on saved candles, never live trades: their best word is HINT.', size: 11, c: p.textMuted),
              ],
            ),
          ]),
        ),
        _line(p, 'Paper only. A verdict is evidence, not an order.', size: 11, c: p.textMuted),
      ]),
    );
  }
}
