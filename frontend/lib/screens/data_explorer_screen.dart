import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';

/// Part 37 (Data Explorer 3 of 4): the SUMMARY on a screen. Read-only: it only asks the backend for /api/v2/summary (Parts 35 + 36),
/// draws the answer and changes nothing (no setting, no position, no order, no file).
/// Four plain cards: WHAT HAPPENED / WHAT WAS TESTED / WHAT WAS LEARNED / WHAT IS UNKNOWN.
/// Rules shown on screen: every number comes with its count; the 4 trade boxes are never added together; no win rate is given;
/// a part that could not be read says UNKNOWN, it is never drawn as zero. Pull down to refresh (the backend keeps one answer for 2 minutes).
class DataExplorerScreen extends StatefulWidget {
  const DataExplorerScreen({super.key});

  @override
  State<DataExplorerScreen> createState() => _DataExplorerScreenState();
}

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<dynamic> _l(Object? v) => v is List ? v : const [];
String _t(Object? v) => (v == null || '$v'.trim().isEmpty) ? '--' : '$v';

String _problem(Object? state) {
  switch (state) {
    case 'off':
      return 'The V2 data API is off. In the owl_data folder make a file named v2_api_enabled that contains 1, then pull down to refresh.';
    case 'old':
      return 'This backend does not have the summary route yet. Install the Part 36 zip, restart the backend, then pull down.';
    default:
      return 'Cannot reach the backend right now. Pull down to try again.';
  }
}

class _DataExplorerScreenState extends State<DataExplorerScreen> {
  Map<String, dynamic>? _data;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final d = await context.read<AppProvider>().fetchSummary();
    if (!mounted) return;
    setState(() {
      _data = d;
      _loading = false;
    });
  }

  Future<void> _refresh() async {
    setState(() => _loading = true);
    await _load();
  }

  Widget _title(AppPalette p, String text, {String? sub}) => Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(text, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, letterSpacing: 0.4, color: p.textPrimary)),
          if (sub != null) Text(sub, style: TextStyle(fontSize: 11, color: p.textMuted)),
        ]),
      );

  Widget _line(AppPalette p, String label, String value, {Color? color}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(flex: 5, child: Text(label, style: TextStyle(fontSize: 13, color: p.textSecondary))),
          Expanded(
              flex: 5,
              child: Text(value,
                  textAlign: TextAlign.right, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: color ?? p.textPrimary))),
        ]),
      );

  Widget _unknownLine(AppPalette p, String text) =>
      Text('UNKNOWN: $text', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: p.warning));

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _data;
    final List<Widget> kids = [];
    if (_loading && d == null) {
      kids.add(const Padding(padding: EdgeInsets.only(top: 80), child: Center(child: CircularProgressIndicator())));
    } else if (d == null || d['what_happened'] is! Map) {
      kids.add(OWLCard(edge: p.warning, child: Text(_problem(d?['state']), style: TextStyle(fontSize: 13, color: p.textPrimary))));
    } else {
      final cov = _m(d['coverage']);
      kids.add(Text(
          'Read-only. Made ${_t(d['made_utc'])}. Every number shows how many it comes from. The trade boxes are never added together. No win rate is given.',
          style: TextStyle(fontSize: 12, color: p.textMuted)));
      kids.add(OWLCard(
          child: Column(children: [
        _line(p, 'Files seen', _t(cov['files_seen'])),
        _line(p, 'Trade boxes read', _t(cov['boxes_read'])),
        _line(p, 'Ledger findings', _t(cov['ledger_findings'])),
      ])));
      kids.add(_happened(p, _m(d['what_happened'])));
      kids.add(_tested(p, _m(d['what_was_tested'])));
      kids.add(_learned(p, _m(_m(d['what_was_learned'])['ledger'])));
      kids.add(_unknown(p, _l(d['what_is_unknown'])));
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

  Widget _happened(AppPalette p, Map<String, dynamic> h) {
    final trades = _m(h['trades']);
    final boxes = _m(trades['boxes']);
    final files = _m(h['data_files']);
    final fl = _l(files['files']);
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, 'WHAT HAPPENED', sub: 'Counts only, from data already on the phone'),
        Text('Trades (each box on its own)', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: p.textSecondary)),
        if (trades['state'] != 'OK') _unknownLine(p, 'the trade archive could not be read (not zero)'),
        for (final k in boxes.keys) _box(p, k, _m(boxes[k])),
        const SizedBox(height: 8),
        Text('Data files', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: p.textSecondary)),
        if (files['state'] != 'OK')
          _unknownLine(p, 'the file list could not be read (not empty)')
        else ...[
          for (final e in _m(files['by_label']).entries) _line(p, '${e.key}', '${e.value} file(s)'),
          if (fl.isNotEmpty)
            Theme(
              data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
              child: ExpansionTile(
                tilePadding: EdgeInsets.zero,
                title: Text('All files (${fl.length}${files['cut'] == true ? ', first ${fl.length}' : ''})',
                    style: TextStyle(fontSize: 12, color: p.textSecondary)),
                children: [
                  for (final f in fl.whereType<Map>())
                    _line(p, '${f['file']}', '${_t(f['label'])}, ${f['rows'] ?? 'rows ?'}'),
                ],
              ),
            ),
          Text('Labels say how much data there is and how good the timestamps are. They say nothing about profit.',
              style: TextStyle(fontSize: 11, color: p.textMuted)),
        ],
      ]),
    );
  }

  Widget _box(AppPalette p, String name, Map<String, dynamic> b) {
    final n = b['trades'] ?? 0;
    final issues = b['data_issues'] ?? 0;
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(name, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
        _line(p, 'Trades', '$n  (wins ${b['wins'] ?? 0}, losses ${b['losses'] ?? 0})'),
        if (n is num && n > 0) _line(p, 'First to last close', '${_t(b['first_close_utc'])} to ${_t(b['last_close_utc'])}'),
        if (issues is num && issues > 0) _line(p, 'Data issues found', '$issues', color: p.warning),
        if (b['trusted_for_research'] != true) Text('Not trusted for research yet.', style: TextStyle(fontSize: 11, color: p.warning)),
      ]),
    );
  }

  Widget _tested(AppPalette p, Map<String, dynamic> t) {
    final by = _m(t['ledger_findings_by_status']);
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, 'WHAT WAS TESTED', sub: 'Only what is written in the Knowledge Ledger counts'),
        _line(p, 'Findings in the Ledger', _t(t['findings'])),
        if (by.isEmpty) Text('No finding yet. Empty means "not written", not "nothing found".', style: TextStyle(fontSize: 12, color: p.textSecondary)),
        for (final e in by.entries) _line(p, '${e.key}', '${e.value}'),
        const SizedBox(height: 4),
        Text('${_t(t['note'])}', style: TextStyle(fontSize: 11, color: p.textMuted)),
      ]),
    );
  }

  Widget _learned(AppPalette p, Map<String, dynamic> led) {
    final list = _l(led['list']).whereType<Map>().toList();
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, 'WHAT WAS LEARNED', sub: 'Not ranked. Sample size and denominator always shown'),
        if (led['state'] == 'UNKNOWN') _unknownLine(p, 'the Ledger could not be read (not empty)'),
        if (led['state'] == 'EMPTY') Text('Nothing written in the Ledger yet.', style: TextStyle(fontSize: 12, color: p.textSecondary)),
        for (final f in list)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${f['finding_id']} v${f['version']}  ${_t(f['name'])}',
                  style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: p.textPrimary)),
              Text(
                  '${_t(f['status'])}  |  Sample ${f['sample_size'] ?? 0} of ${f['denominator'] ?? 0}'
                  '${'${f['denominator_label'] ?? ''}'.isEmpty ? '' : ' (${f['denominator_label']})'}',
                  style: TextStyle(fontSize: 12, color: p.textSecondary)),
            ]),
          ),
        if (led['cut'] == true) Text('Only the first 20 are shown. See More > Knowledge Ledger for all.', style: TextStyle(fontSize: 11, color: p.warning)),
      ]),
    );
  }

  Widget _unknown(AppPalette p, List<dynamic> items) {
    return OWLCard(
      edge: items.isEmpty ? null : p.warning,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, 'WHAT IS UNKNOWN', sub: 'Things we cannot say yet, and why'),
        if (items.isEmpty) Text('Nothing listed.', style: TextStyle(fontSize: 12, color: p.textSecondary)),
        for (final u in items.take(40))
          Padding(
            padding: const EdgeInsets.only(bottom: 4),
            child: Text('- $u', style: TextStyle(fontSize: 12, color: p.textSecondary)),
          ),
        if (items.length > 40) Text('...and ${items.length - 40} more.', style: TextStyle(fontSize: 11, color: p.textMuted)),
      ]),
    );
  }
}
