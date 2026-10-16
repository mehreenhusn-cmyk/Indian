import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// Alerts screen, top: "Yesterday" report that never scrolls away.
///
/// Alerts are a rolling list (and System notices are hidden by default), so an update shown once can vanish.
/// This card is rebuilt by the backend from the permanent closed-trade archive (GET /api/daily-report),
/// is kept on the phone too, and touching the screen cannot remove it. Tap it to open the last 7 days.
class DailyReportCard extends StatefulWidget {
  const DailyReportCard({super.key});

  @override
  State<DailyReportCard> createState() => _DailyReportCardState();
}

class _DailyReportCardState extends State<DailyReportCard> {
  Map<String, dynamic>? _d;
  bool _open = false;
  bool _loading = false;
  String? _error;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _d = context.read<AppProvider>().peekAi('/api/daily-report'); // last report at once, fresh one behind it
    Future.delayed(const Duration(milliseconds: 600), () {
      if (mounted) _load();
    });
    _timer = Timer.periodic(const Duration(seconds: 120), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    if (_loading || !mounted) return;
    _loading = true;
    final prov = context.read<AppProvider>();
    final r = await prov.fetchDailyReport();
    if (!mounted) return;
    setState(() {
      _loading = false;
      if (r != null) {
        _d = r;
        _error = null;
      } else {
        _error = 'Could not refresh. This is the last report.';
      }
    });
  }

  static double _n(dynamic v) => (v is num) ? v.toDouble() : 0.0;
  static int _i(dynamic v) => (v is num) ? v.toInt() : 0;
  static Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  static List<Map<String, dynamic>> _l(dynamic v) =>
      v is List ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];
  static String _s(double v) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}';

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _d;
    if (d == null) {
      return Container(
        width: double.infinity,
        padding: const EdgeInsets.all(12),
        margin: const EdgeInsets.only(bottom: 8),
        decoration: BoxDecoration(color: p.surfaceElevated, borderRadius: BorderRadius.circular(14), border: Border.all(color: p.border.withOpacity(0.7), width: 0.8)),
        child: Text('Yesterday\'s result: loading...', style: context.type.secondary),
      );
    }
    final y = _m(d['yesterday']);
    final t = _m(d['today']);
    final days = _l(d['days']);
    final net = _n(y['net']);
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: (y['trades'] == 0 ? p.border : (net >= 0 ? p.profit : p.loss)).withOpacity(0.55), width: 0.9),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: () => setState(() => _open = !_open),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            // Collapsed = ONE compact line, so today's trades stay visible below.
            Row(children: [
              Text('YESTERDAY', style: context.type.section.copyWith(fontSize: 12)),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  _i(y['trades']) == 0
                      ? 'no trades'
                      : '${_s(net)} · ${_i(y['trades'])} trades · W${_i(y['wins'])} / L${_i(y['losses'])}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w900, color: _i(y['trades']) == 0 ? p.textMuted : (net >= 0 ? p.profit : p.loss)),
                ),
              ),
              Icon(_open ? Icons.expand_less_rounded : Icons.expand_more_rounded, size: 20, color: p.textMuted),
            ]),
            if (_open) ...[
              const Divider(height: 16),
              Text((d['headline'] ?? '').toString(), style: TextStyle(fontSize: 12.5, height: 1.4, color: p.textPrimary)),
              if (_i(t['trades']) > 0) ...[
                const SizedBox(height: 4),
                Text((d['today_line'] ?? '').toString(), style: context.type.metadata),
                const SizedBox(height: 6),
              ],
              if (y['best'] != null && y['worst'] != null)
                Text('Yesterday best: ${_m(y['best'])['sym']} ${_s(_n(_m(y['best'])['pnl']))}   ·   worst: ${_m(y['worst'])['sym']} ${_s(_n(_m(y['worst'])['pnl']))}',
                    style: context.type.secondary.copyWith(fontSize: 12)),
              if (_l(y['by_exit']).isNotEmpty) ...[
                const SizedBox(height: 6),
                Text('How yesterday\'s trades ended', style: context.type.section.copyWith(fontSize: 12)),
                for (final e in _l(y['by_exit']))
                  Padding(
                    padding: const EdgeInsets.only(top: 3),
                    child: Row(children: [
                      Expanded(child: Text('${e['name']}  ·  ${_i(e['n'])} trades', style: context.type.secondary.copyWith(fontSize: 12))),
                      Text(_s(_n(e['net'])), style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: _n(e['net']) >= 0 ? p.profit : p.loss)),
                    ]),
                  ),
              ],
              const SizedBox(height: 8),
              Text('Last 7 days  (${_s(_n(d['week_net']))} USDT)', style: context.type.section.copyWith(fontSize: 12)),
              for (final x in days)
                Padding(
                  padding: const EdgeInsets.only(top: 3),
                  child: Row(children: [
                    SizedBox(width: 78, child: Text('${x['title']}', style: context.type.secondary.copyWith(fontSize: 12, fontWeight: FontWeight.w700))),
                    Expanded(child: Text('${_i(x['trades'])} trades  ·  won ${_i(x['wins'])}, lost ${_i(x['losses'])}', style: context.type.metadata)),
                    Text(_s(_n(x['net'])), style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: _n(x['net']) >= 0 ? p.profit : p.loss)),
                  ]),
                ),
              const SizedBox(height: 6),
              Text((d['note'] ?? '').toString(), style: context.type.metadata),
            ],
            if (_error != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text(_error!, style: context.type.metadata.copyWith(color: p.loss))),
          ]),
        ),
      ),
    );
  }
}
