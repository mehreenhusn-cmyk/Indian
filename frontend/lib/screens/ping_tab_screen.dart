import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/candle_chart.dart';
import '../widgets/ping_widgets.dart';
import '../widgets/report_download_card.dart';

// ---- constants (starting guesses) ----
const Duration _pollInterval = Duration(seconds: 3);

/// Ping tab: Live / Bot / Score / Lead. Polls only while visible.
class PingTabScreen extends StatefulWidget {
  const PingTabScreen({super.key});

  @override
  State<PingTabScreen> createState() => _PingTabScreenState();
}

class _PingTabScreenState extends State<PingTabScreen> with AutomaticKeepAliveClientMixin {
  int _segment = 0;
  Timer? _timer;
  bool _visible = false;

  Map<String, dynamic>? _status;
  Map<String, dynamic>? _live;
  Map<String, dynamic>? _bot;
  Map<String, dynamic>? _score;
  Map<String, dynamic>? _lead;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    // first load when built
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _visible = true;
      _refresh();
      _startPoll();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  void _startPoll() {
    _timer?.cancel();
    _timer = Timer.periodic(_pollInterval, (_) {
      if (_visible && mounted) _refresh();
    });
  }

  void stopPolling() {
    _visible = false;
    _timer?.cancel();
  }

  void resumePolling() {
    _visible = true;
    _refresh();
    _startPoll();
  }

  Future<void> _refresh() async {
    final base = context.read<AppProvider>().baseUrl;
    try {
      final results = await Future.wait([
        _get(base, '/api/ping/status'),
        _get(base, '/api/ping/live'),
        _get(base, '/api/ping/bot'),
        _get(base, '/api/ping/score'),
        _get(base, '/api/ping/lead'),
      ]);
      if (!mounted) return;
      setState(() {
        _status = results[0];
        _live = results[1];
        _bot = results[2];
        _score = results[3];
        _lead = results[4];
      });
    } catch (_) {
      // keep last data; no spinner
    }
  }

  void _openReport() {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (_) => const Padding(
        padding: EdgeInsets.all(12),
        child: SafeArea(
          child: ReportDownloadCard(
            title: 'Ping report',
            description:
                'One text file that explains the Ping Lab to any AI: what was built, why, how it works, the numbers so far and an honest verdict. Send it to any AI.',
            textPath: '/api/ping/report',
            savePath: '/api/ping/report_save',
          ),
        ),
      ),
    );
  }

  Future<Map<String, dynamic>?> _get(String base, String path) async {
    try {
      final res = await http.get(Uri.parse('$base$path')).timeout(const Duration(seconds: 6));
      if (res.statusCode == 200) {
        final decoded = jsonDecode(res.body);
        if (decoded is Map<String, dynamic>) return decoded;
      }
    } catch (_) {}
    return null;
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final p = context.palette;
    final stale = _status?['stale'] == true || _status == null;
    final alive = _status?['alive'] == true;
    final candidates = (_status?['candidate_count'] as num?)?.toInt() ?? 0;
    final rows = (_live?['rows'] as List?)?.cast<dynamic>() ?? const [];
    int buyN = 0, sellN = 0;
    for (final r in rows) {
      if (r is Map) {
        if (r['side'] == 'BUY') buyN++;
        if (r['side'] == 'SELL') sellN++;
      }
    }

    return Scaffold(
      backgroundColor: Colors.transparent,
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 6),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(child: Text('Ping', style: AppTypography.sectionHeading.copyWith(color: p.textPrimary))),
                      TextButton.icon(
                        onPressed: _openReport,
                        icon: const Icon(Icons.description_outlined, size: 18),
                        label: const Text('Report'),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  PingStatusBadge(
                    stale: stale,
                    alive: alive,
                    candidates: candidates,
                    buyAlerts: buyN,
                    sellAlerts: sellN,
                  ),
                  const SizedBox(height: 10),
                  PingSegmentBar(
                    index: _segment,
                    onChanged: (i) => setState(() => _segment = i),
                  ),
                ],
              ),
            ),
            Expanded(child: _body(p)),
          ],
        ),
      ),
    );
  }

  Widget _body(AppPalette p) {
    switch (_segment) {
      case 1:
        return _botBody(p);
      case 2:
        return _scoreBody(p);
      case 3:
        return _leadBody(p);
      default:
        return _liveBody(p);
    }
  }

  Widget _liveBody(AppPalette p) {
    final rows = (_live?['rows'] as List?) ?? const [];
    if (rows.isEmpty) {
      return Center(
        child: Text(
          _live?['stale'] == true
              ? 'Worker offline. Last data unavailable.'
              : 'No pings yet. Waiting for volume spikes.',
          style: AppTypography.secondaryData.copyWith(color: p.textSecondary),
          textAlign: TextAlign.center,
        ),
      );
    }
    return ListView.builder(
      padding: const EdgeInsets.only(bottom: 16),
      itemCount: rows.length,
      itemBuilder: (ctx, i) {
        final row = rows[i];
        if (row is! Map) return const SizedBox.shrink();
        final symbol = (row['symbol'] ?? '').toString();
        return PingLiveRow(
          row: Map<String, dynamic>.from(row),
          onTap: () {
            if (symbol.isEmpty) return;
            showCandleChartSheet(ctx, symbol);
          },
        );
      },
    );
  }

  Widget _botBody(AppPalette p) {
    final bot = _bot ?? {};
    final sentence = (bot['sentence'] ?? 'Paper ping bot has no data yet.').toString();
    final open = (bot['open'] as List?) ?? const [];
    final closed = (bot['closed_recent'] as List?) ?? const [];
    return ListView(
      padding: const EdgeInsets.fromLTRB(12, 0, 12, 16),
      children: [
        PingSummaryCard(sentence: sentence),
        Text('Open (${open.length})', style: AppTypography.metadata.copyWith(color: p.textMuted)),
        const SizedBox(height: 4),
        ...open.take(20).map((t) {
          if (t is! Map) return const SizedBox.shrink();
          final side = t['side']?.toString() ?? '';
          final exp = t['experimental'] == true ? ' · experimental' : '';
          return Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Text(
              '${t['symbol']}  ${t['variant']} $side$exp  entry ${_n(t['entry'])}',
              style: AppTypography.secondaryData.copyWith(color: p.textPrimary),
            ),
          );
        }),
        const SizedBox(height: 12),
        Text('Recent closed', style: AppTypography.metadata.copyWith(color: p.textMuted)),
        ...closed.take(15).map((t) {
          if (t is! Map) return const SizedBox.shrink();
          return Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Text(
              '${t['symbol']} ${t['variant']} ${t['side']}  ${t['exit_reason']}  ${_n(t['pnl_pct'])}%',
              style: AppTypography.metadata.copyWith(color: p.textSecondary),
            ),
          );
        }),
      ],
    );
  }

  Widget _scoreBody(AppPalette p) {
    final s = _score ?? {};
    final sentence = (s['sentence'] ?? 'No live-bot signal comparison yet.').toString();
    final small = s['small_sample'] == true;
    return ListView(
      padding: const EdgeInsets.fromLTRB(12, 0, 12, 16),
      children: [
        PingSummaryCard(sentence: sentence, smallSample: small),
        _kv(p, 'Signals', '${s['signals_total'] ?? 0}'),
        _kv(p, 'TAKE', '${s['take_count'] ?? 0}'),
        _kv(p, 'SKIP', '${s['skip_count'] ?? 0}'),
        _kv(p, 'Loss avoided', _n(s['loss_avoided'])),
        _kv(p, 'Profit missed', _n(s['profit_missed'])),
        _kv(p, 'Net effect', _n(s['net_effect'])),
      ],
    );
  }

  Widget _leadBody(AppPalette p) {
    final L = _lead ?? {};
    final sentence = (L['sentence'] ?? 'No top-10 lead data yet today.').toString();
    final small = L['small_sample'] == true;
    final events = (L['events'] as List?) ?? const [];
    return ListView(
      padding: const EdgeInsets.fromLTRB(12, 0, 12, 16),
      children: [
        PingSummaryCard(sentence: sentence, smallSample: small),
        _kv(p, 'Today entries', '${L['today_count'] ?? 0}'),
        _kv(p, 'Had ping %', _n(L['with_ping_pct'])),
        _kv(p, 'Avg lead min', _n(L['avg_lead_min'])),
        const SizedBox(height: 8),
        ...events.take(20).map((e) {
          if (e is! Map) return const SizedBox.shrink();
          final had = e['had_ping'] == true;
          return Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Text(
              '${e['symbol']} ${e['kind']}  ${had ? "lead ${e['lead_min']} min" : "no ping"}',
              style: AppTypography.metadata.copyWith(color: p.textSecondary),
            ),
          );
        }),
      ],
    );
  }

  Widget _kv(AppPalette p, String k, String v) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          Expanded(child: Text(k, style: AppTypography.secondaryData.copyWith(color: p.textSecondary))),
          Text(v, style: AppTypography.secondaryData.copyWith(color: p.textPrimary, fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }

  String _n(dynamic v) {
    if (v == null) return '—';
    if (v is num) return v.toStringAsFixed(v.abs() >= 10 ? 1 : 2);
    return v.toString();
  }
}
