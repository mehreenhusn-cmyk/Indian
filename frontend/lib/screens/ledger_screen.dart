import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/load_state.dart';
import '../widgets/owl_card.dart';

/// Part 42 (Knowledge Ledger 4 of 4): the LEDGER on a screen. Read-only: it only asks the backend for /api/v2/ledger (Part 41),
/// shows the answer and changes nothing (no setting, no position, no order, no ledger row).
/// Rules shown on screen: every result shows its sample size AND its denominator; findings are NOT ranked by win rate;
/// old versions and failed / rejected ideas stay visible; a gap in the trace chain is shown, never filled in; money is per source, never added.
/// Opened from More > Knowledge Ledger. Pull down to refresh. Tap a finding for its versions, changes and trace chain.
class LedgerScreen extends StatefulWidget {
  const LedgerScreen({super.key});

  @override
  State<LedgerScreen> createState() => _LedgerScreenState();
}

Color _statusColor(AppPalette p, String s) {
  if (s == 'Rejected') return p.negative;
  if (s.startsWith('Validated') || s.startsWith('Approved')) return p.positive;
  if (s == 'Exploratory' || s == 'Watch' || s.startsWith('Promising')) return p.warning;
  return p.textMuted;
}

String _txt(Object? v) => (v == null || '$v'.trim().isEmpty) ? '--' : '$v';

String _num(Object? v, {bool sign = false}) {
  if (v is! num) return '--';
  final n = v.toDouble();
  final s = n.abs().toStringAsFixed(2).replaceAllMapped(RegExp(r'(\d)(?=(\d{3})+\.)'), (m) => '${m[1]},');
  return '${n < 0 ? '-' : (sign && n > 0 ? '+' : '')}$s';
}

/// "42 of 120 (trades)": a result is never shown without its denominator.
String _sample(Map f) {
  final lab = '${f['denominator_label'] ?? ''}'.trim();
  return 'Sample ${f['sample_size'] ?? 0} of ${f['denominator'] ?? 0}${lab.isEmpty ? '' : ' ($lab)'}';
}

String _problem(Object? state) {
  switch (state) {
    case 'off':
      return 'The V2 data API is off. In the owl_data folder make a file named v2_api_enabled that contains 1, then pull down to refresh.';
    case 'old':
      return 'This backend does not have the Ledger routes yet. Install the Part 42 zip, restart the backend, then pull down.';
    default:
      return 'Cannot reach the backend right now. Pull down to try again.';
  }
}

Widget _chip(AppPalette p, String text) => Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: _statusColor(p, text).withOpacity(0.12),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: _statusColor(p, text).withOpacity(0.4)),
      ),
      child: Text(text, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: _statusColor(p, text))),
    );

Widget _row(AppPalette p, String label, String value, {Color? color, bool bold = false}) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(flex: 4, child: Text(label, style: TextStyle(fontSize: 13, color: p.textSecondary))),
        Expanded(
          flex: 6,
          child: Text(value,
              textAlign: TextAlign.right,
              style: TextStyle(fontSize: 13, fontWeight: bold ? FontWeight.w800 : FontWeight.w600, color: color ?? p.textPrimary)),
        ),
      ]),
    );

class _LedgerScreenState extends State<LedgerScreen> {
  static Map<String, dynamic>? _cache; // Part 1b: last good answer stays on screen while a new one loads
  Map<String, dynamic>? _data = _cache;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final d = await context.read<AppProvider>().fetchLedger();
    if (!mounted) return;
    setState(() {
      if (d['findings'] is List) _cache = d;
      _data = (d['findings'] is! List && _cache != null) ? _cache : d; // keep old data when the new try failed
      _loading = false;
    });
  }

  Future<void> _refresh() async {
    setState(() => _loading = true);
    await _load();
  }

  void _openOne(String id) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (_) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.9,
        minChildSize: 0.5,
        maxChildSize: 0.95,
        builder: (_, controller) => _LedgerDetail(findingId: id, controller: controller),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _data;
    final List<Widget> kids = [];
    if (_loading && d == null) {
      kids.add(LoadSpinner(onRetry: _refresh)); // Part 2: 12 s, then Retry
    } else if (d == null || d['findings'] is! List) {
      kids.add(OWLCard(edge: p.warning, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(_problem(d?['state']), style: TextStyle(fontSize: 13, color: p.textPrimary)),
        const SizedBox(height: 8),
        OutlinedButton(onPressed: _refresh, child: const Text('Retry')),
      ])));
    } else {
      final list = (d['findings'] as List).whereType<Map>().toList();
      kids.add(Text('Read-only. Not ranked by win rate. Every result shows its sample size and its denominator. Old versions and failed ideas are kept.',
          style: TextStyle(fontSize: 12, color: p.textMuted)));
      final changes = d['changes'];
      if (changes is List) {
        kids.add(OWLCard(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Changed since ${_txt(d['changes_since'])}',
                style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
            const SizedBox(height: 4),
            if (changes.isEmpty)
              Text('Nothing new.', style: TextStyle(fontSize: 12, color: p.textSecondary))
            else
              for (final c in changes.whereType<Map>().take(20))
                Text(
                    '${c['finding_id']} v${c['version']}: ${c['new_finding'] == true ? 'new finding' : 'changed ' + ((c['changed'] is Map) ? (c['changed'] as Map).keys.join(', ') : '')}',
                    style: TextStyle(fontSize: 12, color: p.textSecondary)),
          ]),
        ));
      }
      if (list.isEmpty) {
        kids.add(OWLCard(
            child: Text(
                'The ledger is empty: nothing is stored yet. Empty means "no finding written", not "nothing was found". Findings appear here once they are added.',
                style: TextStyle(fontSize: 13, color: p.textPrimary))));
      }
      for (final f in list) {
        kids.add(_findingCard(p, f));
      }
      if (d['cut'] == true) {
        kids.add(Text('Only the first 200 findings are shown.', style: TextStyle(fontSize: 11, color: p.warning)));
      }
    }
    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.l, AppSpacing.l, AppSpacing.xl),
        children: [for (final w in kids) Padding(padding: const EdgeInsets.only(bottom: AppSpacing.m), child: w)],
      ),
    );
  }

  Widget _findingCard(AppPalette p, Map f) {
    final status = '${f['status'] ?? ''}';
    return InkWell(
      borderRadius: BorderRadius.circular(16),
      onTap: () => _openOne('${f['finding_id']}'),
      child: OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Text('${f['finding_id']}  v${f['version'] ?? 1}', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: p.textMuted)),
            const Spacer(),
            _chip(p, status),
          ]),
          const SizedBox(height: 6),
          Text(_txt(f['name']), style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary)),
          const SizedBox(height: 4),
          Text(_sample(f), style: TextStyle(fontSize: 12, color: p.textSecondary)),
          if (f['net_result'] != null)
            Text('Net ${_num(f['net_result'], sign: true)} (after costs)',
                style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: (f['net_result'] as num) < 0 ? p.negative : p.textPrimary)),
          if ('${f['limitations'] ?? ''}'.trim().isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text('Limits: ${f['limitations']}', maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 11, color: p.textMuted)),
            ),
        ]),
      ),
    );
  }
}

class _LedgerDetail extends StatefulWidget {
  const _LedgerDetail({required this.findingId, required this.controller});
  final String findingId;
  final ScrollController controller;

  @override
  State<_LedgerDetail> createState() => _LedgerDetailState();
}

class _LedgerDetailState extends State<_LedgerDetail> {
  Map<String, dynamic>? _data;
  bool _loading = true;
  int? _version;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    final d = await context.read<AppProvider>().fetchLedgerOne(widget.findingId, version: _version);
    if (!mounted) return;
    setState(() {
      _data = d;
      _loading = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _data;
    final List<Widget> kids = [];
    if (_loading && d == null) {
      kids.add(LoadSpinner(onRetry: _load)); // Part 2: 12 s, then Retry
    } else if (d == null || d['versions'] is! List) {
      kids.add(OWLCard(edge: p.warning, child: Text(_problem(d?['state']), style: TextStyle(fontSize: 13, color: p.textPrimary))));
    } else {
      final versions = (d['versions'] as List).whereType<Map>().toList();
      final chain = d['chain'] is Map ? Map<String, dynamic>.from(d['chain'] as Map) : <String, dynamic>{};
      final shown = chain['finding'] is Map ? (chain['finding'] as Map)['version'] : (versions.isEmpty ? null : versions.last['version']);
      final f = versions.firstWhere((v) => v['version'] == shown, orElse: () => versions.isEmpty ? <dynamic, dynamic>{} : versions.last);
      kids.add(Text('${widget.findingId}  ${_txt(f['name'])}', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: p.textPrimary)));
      kids.add(Wrap(spacing: 6, runSpacing: 6, children: [
        for (final v in versions)
          ChoiceChip(
            label: Text('v${v['version']}  ${v['status']}', style: const TextStyle(fontSize: 11)),
            selected: v['version'] == shown,
            onSelected: (_) {
              _version = (v['version'] as num).toInt();
              _load();
            },
          ),
      ]));
      if (d['versions_cut'] == true) kids.add(Text('Only the last 50 versions are shown.', style: TextStyle(fontSize: 11, color: p.warning)));
      kids.add(_summary(p, f));
      kids.add(_changes(p, d, shown));
      kids.add(_chain(p, chain));
    }
    return ListView(
      controller: widget.controller,
      padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.l, AppSpacing.l, AppSpacing.xl),
      children: [for (final w in kids) Padding(padding: const EdgeInsets.only(bottom: AppSpacing.m), child: w)],
    );
  }

  Widget _summary(AppPalette p, Map f) {
    String line(String k) => _txt(f[k]);
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [_chip(p, '${f['status'] ?? ''}')]),
        const SizedBox(height: 6),
        _row(p, 'Sample', _sample(f), bold: true),
        _row(p, 'Period', '${line('period_start')} to ${line('period_end')}'),
        _row(p, 'Symbols', line('symbols')),
        _row(p, 'Timeframes', line('timeframes')),
        _row(p, 'Gross', _num(f['gross_result'], sign: true)),
        _row(p, 'Net (after costs)', _num(f['net_result'], sign: true),
            color: f['net_result'] is num && (f['net_result'] as num) < 0 ? p.negative : null, bold: true),
        _row(p, 'Max drawdown', _num(f['max_drawdown'])),
        _row(p, 'Costs assumed', line('cost_assumptions')),
        _row(p, 'Confidence', line('confidence')),
        _row(p, 'Owner approval', line('owner_approval')),
        _row(p, 'Production status', line('production_status')),
        const SizedBox(height: 6),
        Text('What it says: ${line('definition')}', style: TextStyle(fontSize: 12, color: p.textSecondary)),
        Text('Limits: ${line('limitations')}', style: TextStyle(fontSize: 12, color: p.textSecondary)),
        Text('Counterexamples: ${line('counterexamples')}', style: TextStyle(fontSize: 12, color: p.textSecondary)),
        Text('Next test: ${line('next_test')}', style: TextStyle(fontSize: 12, color: p.textSecondary)),
        Text('Research status is not permission to change a live rule.', style: TextStyle(fontSize: 11, color: p.textMuted)),
      ]),
    );
  }

  Widget _changes(AppPalette p, Map<String, dynamic> d, Object? shown) {
    final diffs = d['diffs'];
    Map? mine;
    if (diffs is List) {
      for (final x in diffs.whereType<Map>()) {
        if (x['version'] == shown) mine = x['changed'] is Map ? x['changed'] as Map : null;
      }
    }
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('What changed in this version', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary)),
        const SizedBox(height: 4),
        if (mine == null || mine.isEmpty)
          Text(shown == 1 || shown == null ? 'First version.' : 'No field changed.', style: TextStyle(fontSize: 12, color: p.textSecondary))
        else
          for (final k in mine.keys)
            Text('$k: ${_txt((mine[k] as List?)?.first)}  ->  ${_txt((mine[k] as List?)?.last)}', style: TextStyle(fontSize: 12, color: p.textSecondary)),
      ]),
    );
  }

  Widget _chain(AppPalette p, Map<String, dynamic> c) {
    final gaps = c['gaps'] is List ? (c['gaps'] as List) : const [];
    final per = c['per_source'] is Map ? Map<String, dynamic>.from(c['per_source'] as Map) : <String, dynamic>{};
    final complete = c['complete'] == true;
    return OWLCard(
      edge: complete ? null : p.warning,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Trace chain (where the number comes from)', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary)),
        const SizedBox(height: 4),
        Text(complete ? 'COMPLETE: every record has its snapshots, fee and outcome.' : 'INCOMPLETE: see the gaps below. A gap is never filled in.',
            style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: complete ? p.textPrimary : p.warning)),
        _row(p, 'Records stored', '${c['records'] ?? 0}'),
        _row(p, 'Counterexamples', _txt(c['counterexample_share'])),
        if (per.isEmpty)
          Text('No record IDs are stored for this version.', style: TextStyle(fontSize: 12, color: p.textSecondary)),
        for (final k in per.keys)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Builder(builder: (_) {
              final s = Map<String, dynamic>.from(per[k] as Map);
              return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Source: $k (never added to another source)', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: p.textSecondary)),
                _row(p, 'Records', '${s['records'] ?? 0}'),
                _row(p, 'Gross / fee / net', '${_txt(s['gross'])} / ${_txt(s['fee'])} / ${_txt(s['net'])}'),
                if ((s['fee_missing'] as num?) != null && (s['fee_missing'] as num) > 0)
                  Text('Fee missing on ${s['fee_missing']} record(s).', style: TextStyle(fontSize: 11, color: p.warning)),
              ]);
            }),
          ),
        if (gaps.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text('Gaps (${gaps.length})', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: p.warning)),
          for (final g in gaps.take(30)) Text('- $g', style: TextStyle(fontSize: 11, color: p.textSecondary)),
          if (gaps.length > 30) Text('...and ${gaps.length - 30} more.', style: TextStyle(fontSize: 11, color: p.textMuted)),
        ],
        if (c['items_cut'] == true) Text('Chain items were cut at 500.', style: TextStyle(fontSize: 11, color: p.warning)),
      ]),
    );
  }
}
