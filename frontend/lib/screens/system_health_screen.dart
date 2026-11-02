import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../providers/app_provider_sniper.dart';
import '../widgets/data_doctor_card.dart';
import '../widgets/owl_card.dart';
import '../widgets/sniper_health_tiles.dart';
import 'learning_progress_cards.dart';

/// Part M1b: System Health screen, read-only, on the Part M1a route /api/v2/sys_health (idea of mock picture 10, REAL FACTS ONLY).
/// Shows: one headline (all OK / mostly fine / needs attention), the measured cards two by two (state dot, value, small line), a list of what is NOT MEASURED with the reason, an honest note.
/// A card the backend could not measure says NOT AVAILABLE and is grey; nothing is faked. Pull down to refresh.
/// Round 28 (Diagnostics tab): below the old cards two blocks are added, each loaded on its own so one missing route never hides the other: OwlSniper health (SniperHealthTiles, /api/v2/sniper_health)
/// and the Data Doctor (DataDoctorCard: which coins have candle gaps + the Termux commands; /api/v2/gaps and /api/v2/status). The old part is unchanged. Dart NOT compiled (the APK build is the proof).
class SystemHealthScreen extends StatefulWidget {
  const SystemHealthScreen({super.key});

  @override
  State<SystemHealthScreen> createState() => _SystemHealthScreenState();
}

class _SystemHealthScreenState extends State<SystemHealthScreen> {
  Map<String, dynamic>? _r;
  Map<String, dynamic>? _sh, _gaps, _st;
  bool _busy = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _busy = true);
    final pv = context.read<AppProvider>();
    final all = await Future.wait([pv.fetchSysHealth(), pv.fetchSniperHealth(), pv.fetchV2Gaps(), pv.fetchV2Status()]);
    if (!mounted) return;
    setState(() {
      _r = all[0];
      _sh = all[1];
      _gaps = all[2];
      _st = all[3];
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
        return 'This backend does not have the system health route yet. Install the newest zip, restart the backend, then pull down.';
      default:
        return 'Cannot reach the backend right now. Pull down to try again.';
    }
  }

  Color _c(AppPalette p, String s) => s == 'OK' ? p.profit : s == 'WARN' ? p.warning : s == 'BAD' ? p.loss : p.textMuted;

  Widget _card(AppPalette p, Map<String, dynamic> x) {
    final s = '${x['state'] ?? 'NOT AVAILABLE'}';
    final c = _c(p, s);
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('${x['title'] ?? ''}', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: p.textSecondary))),
          Icon(Icons.circle, size: 10, color: c),
        ]),
        const SizedBox(height: 6),
        Text('${x['value'] ?? '-'}', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: s == 'NOT AVAILABLE' ? p.textMuted : p.textPrimary)),
        const SizedBox(height: 4),
        Text('${x['sub'] ?? ''}', style: TextStyle(fontSize: 11, color: p.textMuted)),
      ]),
    );
  }

  List<Widget> _grid(AppPalette p, List<Map<String, dynamic>> cards) {
    final rows = <Widget>[];
    for (var i = 0; i < cards.length; i += 2) {
      rows.add(Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(child: _card(p, cards[i])),
        const SizedBox(width: 10),
        Expanded(child: i + 1 < cards.length ? _card(p, cards[i + 1]) : const SizedBox()),
      ]));
    }
    return rows;
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final r = _r;
    final List<Widget> kids;
    if (_busy && r == null) {
      kids = [const Padding(padding: EdgeInsets.all(40), child: Center(child: CircularProgressIndicator()))];
    } else if (_bad(r)) {
      kids = [
        OWLCard(edge: p.warning, child: Text(_problem(r), style: TextStyle(fontSize: 13, color: p.textPrimary))),
        SniperHealthTiles(r: _sh),
        DataDoctorCard(gaps: _gaps, status: _st),
      ];
    } else {
      final ok = r!;
      final bad = lpNum(ok['bad']);
      final warn = lpNum(ok['warn']);
      final hc = bad > 0 ? p.loss : warn > 0 ? p.warning : p.profit;
      kids = [
        OWLCard(
          edge: hc,
          child: Row(children: [
            Icon(Icons.circle, size: 14, color: hc),
            const SizedBox(width: 10),
            Expanded(child: Text('${ok['headline'] ?? ''}', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary))),
          ]),
        ),
        ..._grid(p, lpList(ok['cards'])),
        OWLCard(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Not measured yet', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary)),
            const SizedBox(height: 2),
            Text('These are never faked: the backend has no real number for them.', style: TextStyle(fontSize: 11.5, color: p.textMuted)),
            const SizedBox(height: 8),
            for (final x in lpList(ok['not_measured']))
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text('${x['title']}: ${x['why']}', style: TextStyle(fontSize: 12, color: p.textSecondary)),
              ),
          ]),
        ),
        Text('${ok['note'] ?? ''}', style: TextStyle(fontSize: 11, color: p.textMuted)),
        SniperHealthTiles(r: _sh),
        DataDoctorCard(gaps: _gaps, status: _st),
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
