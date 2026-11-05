import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../screens/brain_dashboard_screen.dart';
import '../screens/dual_bot_screen.dart';
import '../screens/results_screen.dart';
import '../screens/sniper_screen.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import 'compare_books.dart';
import 'compare_table.dart';
import 'owl_pressable.dart';
import 'owl_route.dart';
import 'owl_sub_page.dart';

/// R16: the BOOKS STRIP of the Dashboard. ONE line per book: Current Bot, Dual Bot, Brain, Sniper (LEARN). Each line says its own period, so two numbers are never read as the same thing
/// (the old "1985 vs 469" mix-up). Tap a line = open that bot. Books are never added together.
/// It reads the SAME sources and the SAME row builders as widgets/compare_books.dart (mainRow, dualRow, brainRow, learnRow), so Dual "today" is the one R16a source.
/// Each source loads alone (12 s limit): a slow one only turns ITS line into a plain reason. Read only, paper numbers. Dart NOT compiled (the APK build is the proof).
/// Part 7: the LEARN paper-trade count (n of 30) of the newest GOOD Sniper answer, shared with the Dashboard status line (widgets/owl_status_header.dart).
/// null = not known yet (the status line then shows nothing for LEARN; never a made-up 0). Set only here, from the answer this strip already loads: no extra backend call.
final ValueNotifier<int?> learnCountNow = ValueNotifier<int?>(null);

void _publishLearn(Map<String, dynamic> r) {
  final lr = r['learn'];
  final pg = lr is Map ? lr['progress'] : null;
  final n = pg is Map ? pg['n'] : null;
  if (n is num && n.isFinite) learnCountNow.value = n.toInt();
}

class BrainStrip extends StatefulWidget {
  const BrainStrip({super.key});

  @override
  State<BrainStrip> createState() => _BrainStripState();
}

class _BrainStripState extends State<BrainStrip> {
  static const _limit = Duration(seconds: 8);
  static Map<String, dynamic>? _cDual, _cBrain, _cLearn; // Part 1b: last good answers, shown at once on the next visit
  Map<String, dynamic>? _dual = _cDual, _brain = _cBrain, _learn = _cLearn; // null = still loading (first time only)
  int _gen = 0; // a late answer of an older refresh is thrown away

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<Map<String, dynamic>> _safe(Future<Map<String, dynamic>> f) async {
    try {
      return await f.timeout(_limit);
    } catch (_) {
      return {'state': 'error'};
    }
  }

  Future<Map<String, dynamic>> _dualGet(AppProvider pr) async {
    final res = await http.get(Uri.parse('${pr.baseUrl}/api/dual_desk'));
    if (res.statusCode != 200) return {'state': 'error'};
    final d = jsonDecode(res.body);
    return d is Map ? Map<String, dynamic>.from(d) : {'state': 'error'};
  }

  void _load() {
    final pr = context.read<AppProvider>();
    final g = ++_gen;
    // Part 1b: no reset to null any more: old numbers stay until the new answer is good; a failed try keeps them.
    void put(void Function(Map<String, dynamic>) set, void Function(Map<String, dynamic>) keep, Map<String, dynamic>? old, Future<Map<String, dynamic>> f) => _safe(f).then((r) {
          if (!mounted || g != _gen) return;
          final failed = r['state'] == 'error' && old != null;
          if (!failed) keep(r);
          setState(() => set(failed ? old : r));
        });
    put((r) => _dual = r, (r) => _cDual = r, _dual, _dualGet(pr));
    put((r) => _brain = r, (r) => _cBrain = r, _brain, pr.fetchBrainDash());
    put((r) => _learn = r, (r) {
      _cLearn = r;
      _publishLearn(r); // Part 7: the Dashboard status line shows LEARN n/30 from this same answer
    }, _learn, pr.fetchSniperLearn());
  }

  static String _usdt(double v) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)} USDT';

  Widget _line(String name, CompareRow? r, Widget Function() open) {
    final p = context.palette;
    final net = r?.net;
    final hasNum = r != null && net != null;
    final color = !hasNum ? p.textMuted : (net! >= 0 ? p.profit : p.loss);
    final scope = r == null ? 'Loading...' : r.period;
    final small = r == null ? '' : (hasNum ? (r.trades == null ? '' : '${r.trades} closed') : r.note);
    return OWLPressable(
      onTap: () => Navigator.of(context).push(OwlRoute(builder: (_) => open())),
      pressedScale: 0.985,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 9),
        child: Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(name, style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
              Text(scope, style: context.type.metadata, maxLines: 1, overflow: TextOverflow.ellipsis),
            ]),
          ),
          Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text(hasNum ? _usdt(net!) : '--', style: context.type.primary.copyWith(fontWeight: FontWeight.w800, color: color)),
            if (small.isNotEmpty) ConstrainedBox(constraints: const BoxConstraints(maxWidth: 170), child: Text(small, style: context.type.metadata, maxLines: 2, textAlign: TextAlign.right, overflow: TextOverflow.ellipsis)),
          ]),
          Icon(Icons.chevron_right_rounded, size: 20, color: p.textMuted),
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final divider = Divider(height: 1, color: p.border);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(AppSpacing.cardPad, AppSpacing.s, AppSpacing.cardPad, AppSpacing.s),
      decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), border: Border.all(color: p.border)),
      child: Column(children: [
        _line('Dual Bot', _dual == null ? null : dualRow(_dual!), () => const DualBotScreen()),
        divider,
        _line('Brain', _brain == null ? null : brainRow(_brain!), () => const OwlSubPage(title: 'Brain', child: BrainDashboardScreen())),
        divider,
        _line('Sniper (LEARN)', _learn == null ? null : learnRow(_learn!), () => const OwlSubPage(title: 'Sniper', child: SniperScreen())),
        Padding(
          padding: const EdgeInsets.only(top: 4, bottom: 2),
          child: Row(children: [
            Expanded(child: Text('Paper money. Each line has its own period: never add them.', style: context.type.metadata)),
            TextButton(onPressed: _load, style: TextButton.styleFrom(visualDensity: VisualDensity.compact, padding: const EdgeInsets.symmetric(horizontal: 8)), child: const Text('Refresh')),
          ]),
        ),
      ]),
    );
  }
}
