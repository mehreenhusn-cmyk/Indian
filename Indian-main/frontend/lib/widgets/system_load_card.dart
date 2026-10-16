import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// Dashboard "System Load" card - shows how hard the BACKEND is working
/// (CPU / RAM / disk of the process running the bot), the Binance feed, the
/// price broadcaster, candle polling and the AI assistant. Every number comes
/// from GET /api/system (backend telemetry.py, sampled once every ~3s and
/// cached server-side).
///
/// Zero cost to the live price/PnL path:
///  * it owns its own state (setState) and polls via AppProvider.fetchSystem(),
///    which never calls notifyListeners() - so a refresh never rebuilds the
///    rest of the app;
///  * it polls only while the card is on screen (TickerMode is off for
///    offstage tabs) and the app is in the foreground;
///  * collapsed by default - the body is not even built until expanded.
class SystemLoadCard extends StatefulWidget {
  const SystemLoadCard({super.key});

  @override
  State<SystemLoadCard> createState() => _SystemLoadCardState();
}

class _SystemLoadCardState extends State<SystemLoadCard> {
  static const _refresh = Duration(seconds: 3);

  Timer? _timer;
  Map<String, dynamic>? _data;
  bool _expanded = false;
  bool _busy = false;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(_refresh, (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    if (!mounted || _busy) return;
    if (!TickerMode.of(context)) return; // tab not visible
    final life = WidgetsBinding.instance.lifecycleState;
    if (life != null && life != AppLifecycleState.resumed) return;
    _busy = true;
    final res = await context.read<AppProvider>().fetchSystem();
    _busy = false;
    if (!mounted) return;
    setState(() {
      if (res != null && res.isNotEmpty) {
        _data = res;
        _failed = false;
      } else {
        _failed = true;
      }
    });
  }

  // ------------------------------------------------------------- helpers
  static Map<String, dynamic> _m(dynamic v) =>
      v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};

  static double? _n(dynamic v) => v is num ? v.toDouble() : null;

  static String _pct(double? v) => v == null ? '--' : '${v.toStringAsFixed(0)}%';

  static String _mb(double? bytes) =>
      bytes == null ? '--' : '${(bytes / 1048576).toStringAsFixed(0)} MB';

  static String _gb(double? bytes) =>
      bytes == null ? '--' : (bytes / 1073741824).toStringAsFixed(0);

  Color _loadColor(BuildContext c, double? pct) {
    final p = c.palette;
    if (pct == null) return p.textMuted;
    return pct >= 85 ? p.loss : (pct >= 60 ? p.warning : p.profit);
  }

  // ------------------------------------------------------------- widgets
  Widget _tile(BuildContext c, IconData icon, String title, String value, String sub, Color color) {
    final p = c.palette;
    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(AppSpacing.m - 2),
        decoration: BoxDecoration(
          color: p.surfacePrimary,
          borderRadius: BorderRadius.circular(AppSpacing.radiusLarge - 4),
          border: Border.all(color: p.glassBorder, width: 1),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              Icon(icon, size: 14, color: color),
              const SizedBox(width: 6),
              Flexible(
                child: Text(title,
                    overflow: TextOverflow.ellipsis,
                    style: AppTypography.metadata.copyWith(color: p.textMuted, fontSize: 11)),
              ),
            ]),
            const SizedBox(height: 6),
            Text(value,
                style: AppTypography.secondaryData
                    .copyWith(color: p.textPrimary, fontSize: 20, fontWeight: FontWeight.w800)),
            const SizedBox(height: 2),
            Text(sub,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: AppTypography.metadata.copyWith(color: color, fontSize: 10.5)),
          ],
        ),
      ),
    );
  }

  Widget _row(BuildContext c, String label, String value, [Color? color]) {
    final p = c.palette;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          Text(label, style: AppTypography.metadata.copyWith(color: p.textMuted, fontSize: 12)),
          const Spacer(),
          Flexible(
            child: Text(value,
                textAlign: TextAlign.right,
                overflow: TextOverflow.ellipsis,
                style: AppTypography.metadata
                    .copyWith(color: color ?? p.textPrimary, fontSize: 12, fontWeight: FontWeight.w700)),
          ),
        ],
      ),
    );
  }

  Widget _section(BuildContext c, String title) => Padding(
        padding: const EdgeInsets.only(top: 12, bottom: 4),
        child: Text(title,
            style: AppTypography.secondaryData
                .copyWith(color: c.palette.textPrimary, fontSize: 12.5, fontWeight: FontWeight.w700)),
      );

  Widget _body(BuildContext c, Map<String, dynamic> d) {
    final p = c.palette;
    final cpu = _m(d['cpu']);
    final mem = _m(d['mem']);
    final disk = _m(d['disk']);
    final rest = _m(d['rest']);
    final bc = _m(d['broadcast']);
    final poll = _m(d['poll']);
    final ai = _m(d['ai']);
    final feed = _m(d['feed']);

    final cpuPct = _n(cpu['backend_pct']);
    final sysCpu = _n(cpu['system_pct']);
    final sysMem = _n(mem['sys_pct']);
    final diskPct = _n(disk['pct']);
    final restTop = (rest['top'] is List && (rest['top'] as List).isNotEmpty)
        ? _m((rest['top'] as List).first)
        : <String, dynamic>{};
    final alerts = d['alerts'] is List ? (d['alerts'] as List) : const [];

    final kAge = _n(feed['kline_age_s']);
    final feedOk = feed['state'] == 'LIVE' && (kAge ?? 99) < 5;
    final bcAvg = _n(bc['avg_ms']);
    final bcColor = bcAvg == null ? p.textMuted : (bcAvg > 150 ? p.loss : (bcAvg > 60 ? p.warning : p.profit));
    final aiBusy = ai['busy'] == true;
    final aiLast = _n(ai['last_ms']);

    return Padding(
      padding: const EdgeInsets.fromLTRB(AppSpacing.m, 0, AppSpacing.m, AppSpacing.m),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            _tile(c, Icons.memory, 'Backend CPU', _pct(cpuPct),
                sysCpu != null ? 'device ${_pct(sysCpu)}' : '${cpu['cores'] ?? '--'} cores', _loadColor(c, cpuPct)),
            const SizedBox(width: 8),
            _tile(c, Icons.sd_storage_outlined, 'Backend RAM', _mb(_n(mem['rss'])),
                sysMem != null ? 'device ${_pct(sysMem)} used' : 'process memory', _loadColor(c, sysMem)),
          ]),
          const SizedBox(height: 8),
          Row(children: [
            _tile(c, Icons.storage_outlined, 'Disk', _pct(diskPct),
                '${_gb(_n(disk['used']))}/${_gb(_n(disk['total']))} GB', _loadColor(c, diskPct)),
            const SizedBox(width: 8),
            _tile(c, Icons.sync_alt, 'Binance REST', '${rest['per_min'] ?? '--'}/min',
                restTop['ep'] != null ? '${restTop['ep']}' : 'no calls yet', p.accent),
          ]),
          _row(c, 'Backend build', '${d['build'] ?? 'OLD (no tag)'}'),
          _section(c, 'Binance feed'),
          _row(c, 'WebSocket', '${feed['state'] ?? '--'}', feedOk ? p.profit : p.warning),
          _row(c, 'Last candle tick', kAge == null ? '--' : '${kAge.toStringAsFixed(1)}s ago'),
          _row(c, 'Reconnects', '${feed['reconnects'] ?? '--'}'),
          _row(c, 'Symbols (REST-only)', '${feed['symbols'] ?? '--'} (${feed['rest_only'] ?? 0})'),
          _section(c, 'Price broadcast (250ms)'),
          _row(c, 'Tick cost', bcAvg == null ? '--' : '${bcAvg.toStringAsFixed(1)} ms (max ${bc['max_ms'] ?? '--'})', bcColor),
          _row(c, 'Payload / clients',
              '${((_n(bc['bytes']) ?? 0) / 1024).toStringAsFixed(1)} KB / ${bc['clients'] ?? 0}'),
          _row(c, 'Slow clients dropped', '${bc['dropped'] ?? 0}'),
          _section(c, 'Candle polling'),
          _row(c, 'Last sweep', '${poll['cycle_ms'] ?? '--'} ms'),
          _row(c, 'REST fetched / skipped (WS)', '${poll['fetched'] ?? '--'} / ${poll['skipped_ws'] ?? '--'}'),
          _row(c, 'WS candles / duplicates merged', '${poll['ws_candles'] ?? 0} / ${poll['singleflight_hits'] ?? 0}'),
          _section(c, 'AI assistant'),
          _row(c, 'Status', aiBusy ? 'Busy' : 'Idle', aiBusy ? p.warning : p.profit),
          _row(c, 'Calls / errors', '${ai['calls'] ?? 0} / ${ai['errors'] ?? 0}',
              (_n(ai['errors']) ?? 0) > 0 ? p.warning : null),
          _row(c, 'Last reply', aiLast == null ? '--' : '${(aiLast / 1000).toStringAsFixed(1)}s'),
          _section(c, 'Alerts'),
          if (alerts.isEmpty)
            _row(c, 'All clear', 'OK', p.profit)
          else
            for (final a in alerts)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: Row(children: [
                  Icon(Icons.warning_amber_rounded, size: 14, color: p.warning),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text('${_m(a)['msg'] ?? ''}',
                        style: AppTypography.metadata.copyWith(color: p.warning, fontSize: 12)),
                  ),
                ]),
              ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _data;
    final cpu = _m(d?['cpu']);
    final rest = _m(d?['rest']);
    final mem = _m(d?['mem']);
    final alerts = d?['alerts'] is List ? (d!['alerts'] as List) : const [];
    final cpuPct = _n(cpu['backend_pct']);

    final Color chipColor = d == null
        ? p.textMuted
        : (alerts.isNotEmpty ? p.warning : p.profit);
    final String chipText = d == null
        ? (_failed ? 'Offline' : '...')
        : (alerts.isNotEmpty ? '${alerts.length} warning' : 'OK');
    final String summary = d == null
        ? ''
        : 'CPU ${_pct(cpuPct)} · ${_mb(_n(mem['rss']))} · ${rest['per_min'] ?? '--'} REST/min';

    return Container(
      margin: const EdgeInsets.only(bottom: AppSpacing.l),
      decoration: BoxDecoration(
        color: p.surface,
        borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
        border: Border.all(color: p.glassBorder, width: 1),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InkWell(
            borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
            onTap: () {
              AppHaptics.light();
              setState(() => _expanded = !_expanded);
            },
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.m, vertical: AppSpacing.m - 2),
              child: Row(
                children: [
                  Icon(Icons.speed_outlined, size: 16, color: p.accent),
                  const SizedBox(width: 8),
                  Text('System Load',
                      style: AppTypography.secondaryData
                          .copyWith(color: p.textPrimary, fontSize: 13, fontWeight: FontWeight.w700)),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(summary,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: AppTypography.metadata.copyWith(color: p.textMuted, fontSize: 11)),
                  ),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: chipColor.withOpacity(0.16),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(chipText,
                        style: AppTypography.metadata
                            .copyWith(color: chipColor, fontSize: 11, fontWeight: FontWeight.w700)),
                  ),
                  const SizedBox(width: 4),
                  AnimatedRotation(
                    turns: _expanded ? 0.5 : 0,
                    duration: AppMotion.base,
                    curve: AppMotion.standard,
                    child: Icon(Icons.keyboard_arrow_down, color: p.textMuted, size: 20),
                  ),
                ],
              ),
            ),
          ),
          if (_expanded && d != null) _body(context, d),
          if (_expanded && d == null)
            Padding(
              padding: const EdgeInsets.fromLTRB(AppSpacing.m, 0, AppSpacing.m, AppSpacing.m),
              child: Text(
                _failed ? 'Backend abhi jawab nahi de raha. Connect hote hi yahan dikhega.' : 'Loading...',
                style: AppTypography.metadata.copyWith(color: p.textMuted, fontSize: 12),
              ),
            ),
        ],
      ),
    );
  }
}
