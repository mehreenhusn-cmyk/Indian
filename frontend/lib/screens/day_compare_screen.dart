import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';
import 'day_compare_cards.dart';

/// Part X2 (Day calendar + comparison), part 1 of 2: read-only, on the Part X1 route /api/v2/brain_compare.
/// A strip of the last days (Brain net and Current Bot net of each day, tap a day), then the cards of the chosen day (file day_compare_cards.dart, part 2 of 2).
/// Owl Brain, Current Bot and Take-All are three separate numbers, never added. Take-All is a SIMULATION. LIVE is locked and has no tab. Dart NOT compiled (the APK build is the proof).
class DayCompareScreen extends StatefulWidget {
  const DayCompareScreen({super.key});

  @override
  State<DayCompareScreen> createState() => _DayCompareScreenState();
}

class _DayCompareScreenState extends State<DayCompareScreen> {
  Map<String, dynamic>? _r;
  bool _busy = true;
  String _src = 'PAPER';
  String? _day;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _busy = true);
    final r = await context.read<AppProvider>().fetchBrainCompare(_src, _day);
    if (!mounted) return;
    setState(() {
      _r = r;
      _busy = false;
    });
  }

  String _problem(Map<String, dynamic> r) {
    if (r['error'] != null) return '${r['error']}';
    switch (r['state']) {
      case 'off':
        return 'The V2 data API is off. Make the file v2_api_enabled (containing 1) in the owl_data folder, then pull down to refresh.';
      case 'old':
        return 'This backend does not have the comparison route yet. Install the newest zip, restart the backend, then pull down.';
      default:
        return 'Cannot reach the backend right now. Pull down to try again.';
    }
  }

  Widget _sources(AppPalette p) => Wrap(spacing: 8, children: [
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

  Widget _calendar(AppPalette p, Map<String, dynamic> r) {
    final cal = dcList(r['calendar']);
    if (cal.isEmpty) return Text('No closed trade in the last 30 days.', style: TextStyle(fontSize: 12.5, color: p.textMuted));
    final chosen = '${r['day']}';
    return SizedBox(
      height: 84,
      child: ListView(scrollDirection: Axis.horizontal, children: [
        for (final d in cal)
          GestureDetector(
            onTap: () {
              _day = '${d['day']}';
              _load();
            },
            child: Container(
              width: 82,
              margin: const EdgeInsets.only(right: 8),
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: p.surface,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: '${d['day']}' == chosen ? p.accent : p.border, width: '${d['day']}' == chosen ? 2 : 1),
              ),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${d['day']}'.substring(5), style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: p.textPrimary)),
                const SizedBox(height: 4),
                Text('Brain ${dcSg(d['brain_usdt'])}', style: TextStyle(fontSize: 10.5, color: dcNet(p, d['brain_usdt']))),
                Text('Bot ${dcSg(d['bot_usdt'])}', style: TextStyle(fontSize: 10.5, color: dcNet(p, d['bot_usdt']))),
              ]),
            ),
          ),
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
    } else if (r == null || r['state'] != null || r['error'] != null) {
      kids = [OWLCard(edge: p.warning, child: Text(_problem(r ?? <String, dynamic>{'state': 'error'}), style: TextStyle(fontSize: 13, color: p.textPrimary)))];
    } else {
      kids = [
        _sources(p),
        _calendar(p, r),
        Text('Day ${r['day']} (UTC) - $_src', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: p.textSecondary)),
        ...dayCompareCards(p, r),
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
