import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';
import 'learning_progress_cards.dart';
import 'timeline_cards.dart';

/// Part M4b: Brain and Activity timeline (idea of mock picture 13), read-only, on the Part M4a route /api/v2/brain_timeline.
/// ONE UTC day (arrows go to the day before / after), newest line first, clock in IST: what the Owl Brain did (took a trade, put it on WAIT, skipped it, opened, closed) and what the
/// Current Bot did (opened, closed), side by side in time. A small table shows the coins where BOTH acted. Filter chips: All / Brain / Bot. PAPER, SHADOW and REPLAY are separate tabs. LIVE is locked.
/// The two are different trades and are never added. Dart NOT compiled (the APK build is the proof).
class TimelineScreen extends StatefulWidget {
  const TimelineScreen({super.key});

  @override
  State<TimelineScreen> createState() => _TimelineScreenState();
}

class _TimelineScreenState extends State<TimelineScreen> {
  Map<String, dynamic>? _r;
  bool _busy = true;
  String _src = 'PAPER';
  String? _day;
  String _who = 'ALL';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _busy = true);
    final r = await context.read<AppProvider>().fetchBrainTimeline(_src, _day);
    if (!mounted) return;
    setState(() {
      _r = r;
      _busy = false;
    });
  }

  bool _bad(Map<String, dynamic>? r) => r == null || r['state'] != null || r['error'] != null || r['ready'] != true;

  String _problem(Map<String, dynamic>? r) {
    if (r != null && r['error'] != null) return '${r['error']}';
    switch (r == null ? 'error' : r['state']) {
      case 'off':
        return 'The V2 data API is off. Make the file v2_api_enabled (containing 1) in the owl_data folder, then pull down to refresh.';
      case 'old':
        return 'This backend does not have the timeline route yet. Install the newest zip, restart the backend, then pull down.';
      default:
        return 'Cannot reach the backend right now. Pull down to try again.';
    }
  }

  Widget _sources() => Wrap(spacing: 8, children: [
        for (final s in const ['PAPER', 'SHADOW', 'REPLAY'])
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

  Widget _filters() => Wrap(spacing: 8, children: [
        for (final s in const ['ALL', 'BRAIN', 'BOT'])
          ChoiceChip(
            label: Text(s == 'ALL' ? 'All' : s == 'BRAIN' ? 'Brain only' : 'Bot only'),
            selected: _who == s,
            onSelected: (_) => setState(() => _who = s),
          ),
      ]);

  Widget _header(AppPalette p, Map<String, dynamic> r) => Row(children: [
        IconButton(
          icon: const Icon(Icons.chevron_left),
          onPressed: () {
            _day = '${r['prev']}';
            _load();
          },
        ),
        Expanded(child: Text('${r['day']} (UTC)', textAlign: TextAlign.center, style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: p.textPrimary))),
        IconButton(
          icon: const Icon(Icons.chevron_right),
          onPressed: r['next'] == null
              ? null
              : () {
                  _day = '${r['next']}';
                  _load();
                },
        ),
      ]);

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
      final all = lpList(ok['events']);
      final shown = [for (final e in all) if (_who == 'ALL' || e['who'] == _who) e];
      kids = [
        _sources(),
        _header(p, ok),
        tlSummary(p, ok),
        tlCoins(p, ok),
        _filters(),
        if (shown.isEmpty)
          OWLCard(child: Text('No lines for this day and filter.', style: TextStyle(fontSize: 12.5, color: p.textMuted)))
        else
          Column(children: [for (final e in shown) tlEvent(p, e)]),
        if (lpNum(ok['events_cut']) > 0) Text('${lpNum(ok['events_cut']).toInt()} older lines are not shown (the newest ${all.length} are).', style: TextStyle(fontSize: 11, color: p.textMuted)),
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
