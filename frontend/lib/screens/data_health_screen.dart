import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_number.dart';
import '../widgets/owl_row.dart';
import '../widgets/owl_sentence.dart';

/// Part 17d: DATA HEALTH. Answers in plain words: are candles downloading, why is training data missing, is the Sniper learning, when did each background file last write.
/// Data = GET /api/v2/data_health (+ GET /api/v2/sniper_learn for the paper-trade count). Read only. The last-write age of a file is a fact, not a guess that the job is alive.
/// A row that cannot be read says so in words, never a made-up number. Dart NOT compiled.
class DataHealthScreen extends StatefulWidget {
  const DataHealthScreen({super.key});

  @override
  State<DataHealthScreen> createState() => _DataHealthScreenState();
}

class _DataHealthScreenState extends State<DataHealthScreen> {
  Map<String, dynamic>? _h;
  Map<String, dynamic>? _l;

  static Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final a = context.read<AppProvider>();
    final r = await Future.wait([a.fetchDataHealth(), a.fetchSniperLearn()]);
    if (mounted) setState(() {
      _h = r[0];
      _l = r[1];
    });
  }

  static String _ago(Object? s) {
    if (s is! num) return 'never written';
    final v = s.toInt();
    if (v < 120) return '$v s ago';
    if (v < 7200) return '${v ~/ 60} min ago';
    if (v < 172800) return '${v ~/ 3600} h ago';
    return '${v ~/ 86400} days ago';
  }

  void _sheet(String title, List<String> lines) {
    final p = context.palette;
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: p.surface,
      isScrollControlled: true,
      builder: (ctx) => SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(AppSpacing.l),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            Text(title, style: ctx.type.section),
            const SizedBox(height: AppSpacing.m),
            for (final l in lines) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(l, style: ctx.type.secondary.copyWith(height: 1.35))),
          ]),
        ),
      ),
    );
  }

  Widget _candles(Map<String, dynamic> c) {
    final on = c['switch'] == 'ON';
    final owner = c['owner_off'] == true;
    final running = c['runner_running'] == true;
    return OwlListCard(children: [
      OwlRow(
        title: 'Candle download',
        sub: on ? 'ON. If it stops by accident, it turns on again within 10 minutes.' : owner ? 'OFF. You switched it off. To start: python3 backend/v2_candles.py --on' : 'OFF without your switch. It turns on by itself soon.',
        trailing: OwlPill(on ? 'ON' : 'OFF', tone: on ? 'good' : owner ? 'warn' : 'bad'),
      ),
      OwlRow(
        title: 'Background runner',
        sub: running ? 'Working (heartbeat ${_ago(c['runner_beat_age_s'])})' : 'No heartbeat. The backend starts it again within 2 minutes.',
        trailing: OwlPill(running ? 'RUNNING' : 'NOT SEEN', tone: running ? 'good' : 'warn'),
      ),
      if (_m(c['ws']).isNotEmpty) _ws(_m(c['ws'])),
    ]);
  }

  /// Part 17e: the live websocket candles. LIVE only when the backend says connected AND its status file is fresh (a stale file never shows LIVE).
  Widget _ws(Map<String, dynamic> w) {
    final fresh = w['status_age_s'] is num && (w['status_age_s'] as num) < 180;
    final live = w['connected'] == true && fresh;
    final err = '${w['last_error'] ?? ''}';
    return OwlRow(
      title: 'Live candles (websocket)',
      sub: live ? '${w['coins'] ?? 0} coins. ${w['saved'] ?? 0} saved live, ${w['skipped_no_prev'] ?? 0} left to the download.' : (err.isNotEmpty ? err : '${w['note'] ?? 'Not connected'}'),
      trailing: OwlPill(live ? 'LIVE' : 'OFFLINE', tone: live ? 'good' : 'warn'),
      onTap: () => _sheet('Live candles', [
        'One connection brings each closed 3m and 5m candle the moment it closes. The download fills only what is missing.',
        'A live candle is saved only if the candle before it is known. Otherwise it is left to the download, so no hole is hidden.',
        'Reconnects so far: ${w['reconnects'] ?? 0}. Status ${_ago(w['status_age_s'])}.',
        if (err.isNotEmpty) 'Last error: $err',
      ]),
    );
  }

  Widget _history(Map<String, dynamic> h) {
    final by = _m(h['by_source']);
    final lines = [for (final x in (h['lines'] is List ? h['lines'] as List : const [])) '$x'];
    if (by.isEmpty) return Text(lines.isNotEmpty ? lines.first : 'No closed trades to check yet.', style: context.type.secondary);
    const names = {'dual': 'Dual Bot trades', 'brain': 'Brain trades', 'main': 'Main bot trades'};
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      OwlListCard(children: [
        for (final k in by.keys)
          () {
            final s = _m(by[k]);
            return OwlRow(
              title: names[k] ?? k,
              sub: '${s['records'] ?? 0} trades: ${s['ready'] ?? 0} ready, ${s['needs_fetch'] ?? 0} to download, ${s['too_old'] ?? 0} too old',
              onTap: () => _sheet(names[k] ?? k, [
                'ready: candles are saved, the trade can teach the Sniper.',
                'to download: candles are missing, the downloader fills them (60 requests every 10 minutes).',
                'known gap: Binance had no candles for that time, it cannot be filled.',
                'too old: older than Binance keeps for this chart, it cannot be filled. Only new trades will help.',
                'too recent: the candle is not closed yet, wait.',
                'Now: ${s['records'] ?? 0} trades, ${s['ready'] ?? 0} ready, ${s['needs_fetch'] ?? 0} to download, ${s['known_gap'] ?? 0} known gap, ${s['too_old'] ?? 0} too old, ${s['too_recent'] ?? 0} too recent.',
              ]),
            );
          }(),
      ]),
      const SizedBox(height: AppSpacing.s),
      Text('${h['requests_needed'] ?? 0} download requests still needed. Sources are never added together.', style: context.type.metadata),
    ]);
  }

  Widget _learning(Map<String, dynamic> g) {
    final st = '${g['state']}';
    if (g['state'] == null) return Text('The autopilot has not written its file yet. It needs saved trades and candles first.', style: context.type.secondary);
    final prog = _m(_m(_m(_l)['learn'])['progress']);
    return OwlListCard(children: [
      OwlRow(
        title: 'Autopilot',
        sub: '${g['n_train'] ?? 0} training and ${g['n_test'] ?? 0} test examples, ${g['days'] ?? 0} days, ${_ago(g['age_s'])}',
        trailing: OwlPill(st == 'LEARNED' ? 'LEARNED' : 'LEARNING', tone: st == 'LEARNED' ? 'good' : 'warn'),
        onTap: () => _sheet('Autopilot', [
          st == 'LEARNED' ? 'LEARNED = on days it never saw, the model beat taking every signal, after fees. Not a profit promise.' : 'LEARNING = still collecting. It needs about 6 whole days of examples before it can be judged.',
          for (final r in (g['reasons'] is List ? g['reasons'] as List : const [])) '$r',
        ]),
      ),
      if (prog.isNotEmpty) OwlRow(title: 'Paper trades (LEARN lane)', sub: '${prog['text'] ?? '${prog['n'] ?? 0} of ${prog['target'] ?? '?'}'}'),
    ]);
  }

  Widget _jobs(List<dynamic> jobs) {
    return OwlListCard(children: [
      for (final j in jobs) OwlRow(title: '${_m(j)['label']}', sub: 'Last written ${_ago(_m(j)['age_s'])}'),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final h = _h;
    Widget body;
    if (h == null) {
      body = const Padding(padding: EdgeInsets.only(top: AppSpacing.l), child: OwlRowSkeleton(rows: 4));
    } else if (h['state'] != 'OK') {
      final s = '${h['state']}';
      body = Text(s == 'off' ? 'The V2 data API is switched off.' : s == 'old' ? 'This backend has no data-health route yet. Install the newest backend zip and restart.' : 'Cannot read this right now. Pull down to try again.', style: context.type.secondary);
    } else {
      body = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const OwlSectionLabel('Candles'),
        _candles(_m(h['candles'])),
        const OwlSectionLabel('Why training data is missing'),
        _history(_m(h['history'])),
        const OwlSectionLabel('Is it learning'),
        _learning(_m(h['learning'])),
        const OwlSectionLabel('Background files'),
        _jobs(h['jobs'] is List ? h['jobs'] as List : const []),
        const SizedBox(height: AppSpacing.s),
        Text('Last written is a fact about the file. If it stays old for many hours, the job is not working: open App Problems.', style: context.type.metadata),
      ]);
    }
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.m, AppSpacing.l, AppSpacing.xl),
        children: [const OwlSentence('Is the data coming and is the Sniper learning', lines: ['Read only. All numbers are paper money.']), body],
      ),
    );
  }
}
