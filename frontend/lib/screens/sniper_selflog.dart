import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/load_state.dart';
import '../widgets/owl_card.dart';

/// Part 44 (FILE 53): SNIPER SELF LOG. Plain lines, newest first: what Sniper LEARNED, which MISTAKES it made, what CHANGED.
/// Read only: it asks GET /api/v2/sniper_selflog and shows what the backend says; nothing is worked out here and nothing is opened, closed or changed.
/// Layout (Study Lab rule): ONE summary on top (counts), filter chips, the newest lines, older lines collapsed. The note under the summary is said openly:
/// Sniper changes nothing by itself (every check is report only), so 'Changed' only lists the owner's switches. LEARN wins are not listed one by one (the LEARN n of 30 bar counts them).
/// Time is the phone's local time. LoadSpinner (Part 1): 12 s then Retry. Use: SniperSelfLog(). Dart NOT compiled (the APK build is the proof).

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> _l(Object? v) => v is List ? [for (final e in v) _m(e)] : <Map<String, dynamic>>[];
int _i(Object? v) => v is num ? v.toInt() : 0;

const _showFirst = 12;
const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

class SniperSelfLog extends StatefulWidget {
  const SniperSelfLog({super.key});

  @override
  State<SniperSelfLog> createState() => _SniperSelfLogState();
}

class _SniperSelfLogState extends State<SniperSelfLog> {
  Map<String, dynamic>? _data;
  String _filter = 'ALL';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _data = null);
    final d = await context.read<AppProvider>().fetchSniperSelfLog();
    if (!mounted) return;
    setState(() => _data = d);
  }

  Color _kc(AppPalette p, String k) => k == 'LEARNED' ? p.profit : (k == 'MISTAKE' ? p.loss : p.accent);

  String _kw(String k) => k == 'LEARNED' ? 'LEARNED' : (k == 'MISTAKE' ? 'MISTAKE' : 'CHANGED');

  String _time(Object? ts) {
    final t = DateTime.fromMillisecondsSinceEpoch(_i(ts) * 1000).toLocal();
    String two(int x) => x < 10 ? '0$x' : '$x';
    return '${t.day} ${_months[t.month - 1]} ${two(t.hour)}:${two(t.minute)}';
  }

  Widget _chip(String text, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: c.withOpacity(0.15), borderRadius: BorderRadius.circular(20)),
        child: Text(text, style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w800, color: c)),
      );

  Widget _title(AppPalette p) => Text('Sniper self log', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary));

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

  Widget _row(AppPalette p, Map<String, dynamic> e) {
    final k = '${e['kind']}';
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [_chip(_kw(k), _kc(p, k)), const SizedBox(width: 8), Text(_time(e['ts']), style: TextStyle(fontSize: 10.5, color: p.textMuted))]),
        _line(p, '${e['text']}', size: 12, c: p.textPrimary),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _data;
    if (d == null) return OWLCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [_title(p), LoadSpinner(onRetry: _load)]));
    final st = '${d['state']}';
    if (st == 'off') return _note(p, 'The V2 data API or the Sniper is switched off, so the self log cannot be read.', edge: p.textMuted, chip: 'OFF');
    if (st == 'old') return _note(p, 'This backend has no self log route yet. Install the newest backend zip and restart the backend.', edge: p.warning, chip: 'OLD BACKEND');
    if (st == 'busy') return _note(p, '${d['text'] ?? 'The self log is being built. Try again in a minute.'}', edge: p.warning, chip: 'BUSY', retry: true);
    if (st == 'broken') return _note(p, '${d['text'] ?? 'The self log file is broken.'}', edge: p.loss, chip: 'BROKEN');
    if (st == 'error') return _note(p, '${d['text'] ?? 'The self log could not be read.'}', edge: p.loss, chip: 'ERROR', retry: true);
    final cnt = _m(d['counts']);
    final all = _l(d['entries']);
    final list = _filter == 'ALL' ? all : [for (final e in all) if ('${e['kind']}' == _filter) e];
    final fresh = list.length <= _showFirst ? list : list.sublist(0, _showFirst);
    final older = list.length <= _showFirst ? <Map<String, dynamic>>[] : list.sublist(_showFirst);
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [Expanded(child: _title(p)), _chip('${_i(d['n_total'])} notes', p.textMuted)]),
        const SizedBox(height: 8),
        Text('${d['text'] ?? ''}', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
        _line(p, 'Sniper changes nothing by itself: every check is report only. "Changed" lists only the owner\'s switches.', size: 11.5),
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Wrap(spacing: 6, runSpacing: 6, children: [
            for (final k in const ['LEARNED', 'MISTAKE', 'CHANGED']) if (_i(cnt[k]) > 0) _chip('${_kw(k)} ${_i(cnt[k])}', _kc(p, k)),
          ]),
        ),
        Padding(
          padding: const EdgeInsets.only(top: 10),
          child: Wrap(spacing: 8, children: [
            for (final f in const ['ALL', 'LEARNED', 'MISTAKE', 'CHANGED'])
              ChoiceChip(
                label: Text(f == 'ALL' ? 'All' : (f == 'LEARNED' ? 'Learned' : (f == 'MISTAKE' ? 'Mistakes' : 'Changed')), style: const TextStyle(fontSize: 12)),
                selected: _filter == f,
                onSelected: (_) => setState(() => _filter = f),
              ),
          ]),
        ),
        if (list.isEmpty) _line(p, st == 'EMPTY' ? 'Nothing to list yet. Lessons appear here after the first LEARN trades and reports.' : 'Nothing in this group yet.', c: p.textMuted),
        for (final e in fresh) _row(p, e),
        if (older.isNotEmpty)
          Theme(
            data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
            child: ExpansionTile(
              tilePadding: EdgeInsets.zero,
              childrenPadding: EdgeInsets.zero,
              title: Text('Older notes (${older.length})', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: p.textSecondary)),
              expandedCrossAxisAlignment: CrossAxisAlignment.start,
              children: [for (final e in older) _row(p, e)],
            ),
          ),
        _line(p, 'Paper only. A note is a record, not an order. The newest 30 LEARN events are read at each look; wins are counted in the LEARN n of 30 bar.', size: 11, c: p.textMuted),
      ]),
    );
  }
}
