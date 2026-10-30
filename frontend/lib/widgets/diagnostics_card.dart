import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/diag_status.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// Part 24: fills the shared 6-check model (models/diag_status.dart) from the REAL status keys.
/// null = not known = grey UNKNOWN, never a made-up green.
///  backend   : provider.error (null + first status received = answering)
///  ws        : provider.wsConnected + provider.liveAgeSec
///  market    : status['market_data_state']
///  scanner   : status['server_ts'] - status['last_poll_cycle_ts'] <= 60 s (poll cycle is 8 s)
///  strategy  : status['last_error'] starts with BOT CRASHED = bad, status['symbols_tracked'] > 0 = ready
///  execution : provider.unprotectedPositions not empty = bad, else status['last_guard_tick']['ok']
///              (no guard tick yet, e.g. paper mode = unknown)
DiagStatus buildDiagStatus(AppProvider p) {
  final st = p.status;
  final serverTs = p.serverTs;
  final bool? backend = p.error != null ? false : (serverTs != null ? true : null);

  final cycle = (st['last_poll_cycle_ts'] as num?)?.toDouble();
  final bool? scanner = (serverTs != null && cycle != null) ? (serverTs - cycle) <= 60 : null;

  final err = st['last_error'];
  final tracked = (st['symbols_tracked'] as num?)?.toInt();
  bool? strategy;
  if (err is String && err.startsWith('BOT CRASHED')) {
    strategy = false;
  } else if (tracked != null && tracked > 0) {
    strategy = true;
  }

  final guard = st['last_guard_tick'];
  bool? execution;
  if (p.unprotectedPositions.isNotEmpty) {
    execution = false;
  } else if (guard is Map && guard['ok'] is bool) {
    execution = guard['ok'] as bool;
  }

  return DiagStatus.fromInputs(
    backendReachable: backend,
    wsConnected: p.wsConnected,
    liveAgeSec: p.liveAgeSec?.toDouble(),
    marketDataState: st['market_data_state'] as String?,
    scannerActive: scanner,
    strategyReady: strategy,
    executionHealthy: execution,
  );
}

/// Collapsible engineering/ops diagnostics panel for the Dashboard.
///
/// Every number here is real, sourced entirely from AppProvider's typed
/// telemetry accessors over /api/status - see api_server.py's
/// _display_status() (feed_age_sec/open_pnl/stats_mode), market_ws.py
/// (feed_last_update_ts/feed_latency_net_ms/feed_latency_engine_ms) and
/// protection_manager.py (unprotected_positions/last_guard_tick) for the
/// backend contracts this renders. Nothing here is a placeholder or a
/// client-side guess - when the backend hasn't reported a number yet,
/// this shows "--", never a fabricated value.
class DiagnosticsCard extends StatefulWidget {
  const DiagnosticsCard({super.key});

  @override
  State<DiagnosticsCard> createState() => _DiagnosticsCardState();
}

class _DiagnosticsCardState extends State<DiagnosticsCard> {
  bool _expanded = false;
  bool _collapsedTick = false;
  Timer? _ticker;

  // Feed-age ticking baseline: the backend reports feed_age_sec as of ITS
  // OWN server_ts (see AppProvider.feedAgeSec doc) - this widget then adds
  // locally-elapsed time on top of that one authoritative number every
  // second, exactly like position_card.dart's own "Open Xm Ys" ticker, so
  // the badge visibly counts up between pushes instead of jumping once/sec.
  double? _feedAgeBaseSec;
  DateTime? _feedAgeBaseAt;
  double? _lastSeenServerTs;

  // One-shot "App Display" latency - recomputed only when a genuinely NEW
  // payload (a new server_ts) arrives, never continuously. Continuously
  // re-deriving this from a fixed server_ts would just re-measure "how
  // long ago did the last update arrive", which is already the Feed Age
  // badge's job - this number instead answers "how long did THAT specific
  // packet take to reach the phone".
  double? _appLatencyMs;

  // Per-error-code dismiss state: dismissing hides that code's banner only
  // until a NEWER occurrence (by its own `ts`) of the same code fires, so a
  // fresh recurrence of the same problem is never silently swallowed.
  final Map<int, double> _dismissedUntilTs = {};

  static const List<int> _actionableCodes = [-4120, -2019, -2022];

  @override
  void initState() {
    super.initState();
    // 1 s while the card is open (live numbers), 2 s while collapsed (only the small "Feed: x s ago" badge).
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted) return;
      if (_expanded || (_collapsedTick = !_collapsedTick)) setState(() {});
    });
  }

  @override
  void dispose() {
    _ticker?.cancel();
    super.dispose();
  }

  void _syncTelemetryBaseline(AppProvider provider) {
    final serverTs = provider.serverTs;
    if (serverTs == null || serverTs == _lastSeenServerTs) return;
    _lastSeenServerTs = serverTs;
    _feedAgeBaseSec = provider.feedAgeSec;
    _feedAgeBaseAt = DateTime.now();
    final nowMs = DateTime.now().toUtc().millisecondsSinceEpoch.toDouble();
    final delta = nowMs - serverTs * 1000.0;
    _appLatencyMs = delta.isFinite ? delta.clamp(0.0, 60000.0) : null;
  }

  double? get _liveFeedAgeSec {
    if (_feedAgeBaseSec == null || _feedAgeBaseAt == null) return null;
    return _feedAgeBaseSec! +
        DateTime.now().difference(_feedAgeBaseAt!).inMilliseconds / 1000.0;
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<AppProvider>(
      builder: (context, provider, child) {
        _syncTelemetryBaseline(provider);
        final feedAge = _liveFeedAgeSec;
        final connected = provider.wsConnected;
        final marketState = provider.marketDataState;
        final reconnects = provider.wsReconnectCountFromStatus;
        final netMs = provider.feedLatencyNetMs;
        final engineMs = provider.feedLatencyEngineMs;
        final unprotected = provider.unprotectedPositions;
        final errors = provider.recentApiErrors;
        final diag = buildDiagStatus(provider);

        // Feed Age color: green <3s, amber >5s, orange in between - matches
        // the exact thresholds asked for ("green agar <3s, yellow agar >5s").
        Color feedColor;
        String feedText;
        if (feedAge == null) {
          feedColor = context.palette.textMuted;
          feedText = 'Feed: --';
        } else {
          feedColor = feedAge < 3
              ? context.palette.profit
              : (feedAge > 5 ? context.palette.warning : Colors.orangeAccent);
          feedText = 'Feed: ${feedAge.toStringAsFixed(1)}s ago';
        }

        // Newest actionable error that hasn't already been dismissed for
        // its own occurrence (errors list is newest-first).
        Map<String, dynamic>? bannerError;
        for (final e in errors) {
          final code = (e['code'] as num?)?.toInt();
          if (code == null || !_actionableCodes.contains(code)) continue;
          final ts = (e['ts'] as num?)?.toDouble() ?? 0.0;
          final dismissedUntil = _dismissedUntilTs[code];
          if (dismissedUntil != null && ts <= dismissedUntil) continue;
          bannerError = e;
          break;
        }

        return Container(
          margin: const EdgeInsets.only(bottom: AppSpacing.l),
          decoration: BoxDecoration(
            color: context.palette.surface,
            borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
            border: Border.all(color: context.palette.glassBorder, width: 1),
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
                      Icon(Icons.monitor_heart_outlined, size: 16, color: context.palette.accent),
                      const SizedBox(width: 8),
                      Text(
                        'Diagnostics',
                        style: AppTypography.secondaryData.copyWith(color: context.palette.textPrimary, fontSize: 13, fontWeight: FontWeight.w700),
                      ),
                      const Spacer(),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: feedColor.withOpacity(0.16),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Text(
                          feedText,
                          style: AppTypography.metadata.copyWith(color: feedColor, fontSize: 11, fontWeight: FontWeight.w700),
                        ),
                      ),
                      if (unprotected.isNotEmpty) ...[
                        const SizedBox(width: 6),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
                          decoration: BoxDecoration(
                            color: context.palette.loss.withOpacity(0.18),
                            borderRadius: BorderRadius.circular(8),
                            border: Border.all(color: context.palette.loss, width: 1),
                          ),
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(Icons.gpp_bad_outlined, size: 12, color: context.palette.loss),
                              const SizedBox(width: 3),
                              Text(
                                '${unprotected.length}',
                                style: AppTypography.metadata.copyWith(color: context.palette.loss, fontSize: 11, fontWeight: FontWeight.w700),
                              ),
                            ],
                          ),
                        ),
                      ],
                      const SizedBox(width: 4),
                      AnimatedRotation(
                        turns: _expanded ? 0.5 : 0,
                        duration: AppMotion.base,
                        curve: AppMotion.standard,
                        child: Icon(Icons.keyboard_arrow_down, color: context.palette.textMuted, size: 20),
                      ),
                    ],
                  ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(AppSpacing.m, 0, AppSpacing.m, AppSpacing.m - 2),
                child: _HealthStrip(diag: diag),
              ),
              AnimatedSize(
                duration: AppMotion.base,
                curve: AppMotion.standard,
                alignment: Alignment.topCenter,
                child: !_expanded
                    ? const SizedBox(width: double.infinity, height: 0)
                    : Padding(
                        padding: const EdgeInsets.fromLTRB(AppSpacing.m, 0, AppSpacing.m, AppSpacing.m),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            if (bannerError != null) ...[
                              _ApiErrorBanner(
                                error: bannerError,
                                onDismiss: () {
                                  final code = (bannerError!['code'] as num).toInt();
                                  final ts = (bannerError['ts'] as num?)?.toDouble() ??
                                      DateTime.now().millisecondsSinceEpoch / 1000.0;
                                  setState(() => _dismissedUntilTs[code] = ts);
                                },
                              ),
                              const SizedBox(height: 10),
                            ],
                            _HealthDetail(diag: diag),
                            const SizedBox(height: 10),
                            _DiagRow(
                              label: 'Socket',
                              value: connected ? 'LIVE' : 'DOWN',
                              valueColor: connected ? context.palette.profit : context.palette.loss,
                              trailing: 'Reconnects: $reconnects',
                            ),
                            const SizedBox(height: 6),
                            _DiagRow(
                              label: 'Feed',
                              value: marketState,
                              valueColor: marketState == 'LIVE'
                                  ? context.palette.profit
                                  : (marketState == 'STALE' || marketState == 'RECONNECTING' || marketState == 'REST'
                                      ? context.palette.warning
                                      : context.palette.loss),
                            ),
                            const SizedBox(height: 6),
                            _DiagRow(
                              label: 'Latency',
                              value: netMs != null
                                  ? 'Net: ${netMs.toStringAsFixed(0)}ms'
                                      '${engineMs != null ? ' | Engine: ${engineMs.toStringAsFixed(1)}ms' : ''}'
                                      '${_appLatencyMs != null ? ' | App: ${_appLatencyMs!.toStringAsFixed(0)}ms' : ''}'
                                  : 'No data yet',
                              valueColor: context.palette.textSecondary,
                              monospace: true,
                            ),
                            const SizedBox(height: 6),
                            _DiagRow(
                              label: 'Signal lag',
                              value: provider.signalLagLastS != null
                                  ? 'Last ${provider.signalLagLastS!.toStringAsFixed(1)}s'
                                      ' | Avg ${provider.signalLagAvgS?.toStringAsFixed(1) ?? '--'}s'
                                      ' | Worst ${provider.signalLagWorstS?.toStringAsFixed(1) ?? '--'}s'
                                      ' (${provider.signalLagCount})'
                                  : 'No trade yet',
                              valueColor: provider.signalLagLastS == null
                                  ? context.palette.textSecondary
                                  : (provider.signalLagLastS! <= 5.0
                                      ? context.palette.profit
                                      : context.palette.warning),
                              monospace: true,
                            ),
                            if (provider.lastGuardTick != null) ...[
                              const SizedBox(height: 6),
                              _GuardTickRow(tick: provider.lastGuardTick!),
                            ],
                            if (unprotected.isNotEmpty) ...[
                              const SizedBox(height: 10),
                              _UnprotectedWarning(positions: unprotected),
                            ],
                          ],
                        ),
                      ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _DiagRow extends StatelessWidget {
  final String label;
  final String value;
  final Color valueColor;
  final String? trailing;
  final bool monospace;

  const _DiagRow({
    required this.label,
    required this.value,
    required this.valueColor,
    this.trailing,
    this.monospace = false,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 62,
          child: Text(label, style: AppTypography.secondaryData.copyWith(color: context.palette.textMuted, fontSize: 12)),
        ),
        Expanded(
          child: Text(
            value,
            style: AppTypography.secondaryData.copyWith(
              color: valueColor,
              fontSize: 12,
              fontWeight: FontWeight.w700,
              fontFamily: monospace ? 'monospace' : null,
            ),
          ),
        ),
        if (trailing != null)
          Text(trailing!, style: AppTypography.metadata.copyWith(color: context.palette.textMuted, fontSize: 11)),
      ],
    );
  }
}

/// One-line summary of the most recent continuous protection guard_tick()
/// pass (protection_manager.py) - runs every ~3.5s whenever live trading is
/// on and Binance is the active exchange.
class _GuardTickRow extends StatelessWidget {
  final Map<String, dynamic> tick;
  const _GuardTickRow({required this.tick});

  @override
  Widget build(BuildContext context) {
    if (tick['skipped'] == true) {
      return _DiagRow(
        label: 'Guard',
        value: (tick['reason'] as String?) ?? 'skipped',
        valueColor: context.palette.textMuted,
      );
    }
    final checked = (tick['checked'] as num?)?.toInt() ?? 0;
    final replaced = (tick['sl_replaced'] as num?)?.toInt() ?? 0;
    final failed = (tick['failed'] as num?)?.toInt() ?? 0;
    final ok = tick['ok'] == true;
    return _DiagRow(
      label: 'Guard',
      value: '$checked checked'
          '${replaced > 0 ? ' · $replaced SL re-placed' : ''}'
          '${failed > 0 ? ' · $failed failed' : ''}',
      valueColor: ok ? context.palette.profit : context.palette.warning,
    );
  }
}

class _UnprotectedWarning extends StatelessWidget {
  final List<Map<String, dynamic>> positions;
  const _UnprotectedWarning({required this.positions});

  @override
  Widget build(BuildContext context) {
    final symbols = positions.map((p) => p['symbol']?.toString() ?? '?').join(', ');
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.m - 2),
      decoration: BoxDecoration(
        color: context.palette.loss.withOpacity(0.14),
        borderRadius: BorderRadius.circular(AppSpacing.radiusSmall + 2),
        border: Border.all(color: context.palette.loss.withOpacity(0.5)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.warning_amber_rounded, color: context.palette.loss, size: 16),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              '${positions.length} live position${positions.length == 1 ? '' : 's'} missing '
              'a resting stop-loss on Binance: $symbols. The guard loop retries every ~3.5s.',
              style: AppTypography.metadata.copyWith(color: context.palette.loss, fontSize: 11.5, fontWeight: FontWeight.w600),
            ),
          ),
        ],
      ),
    );
  }
}

/// Dismissible inline banner for a recent Binance API error - only shown
/// for the codes actually worth surfacing to the user (-4120/-2019/-2022);
/// every other code is still logged by the backend but not banner-worthy.
class _ApiErrorBanner extends StatelessWidget {
  final Map<String, dynamic> error;
  final VoidCallback onDismiss;
  const _ApiErrorBanner({required this.error, required this.onDismiss});

  String _describe(int code) {
    switch (code) {
      case -4120:
        return 'Order would immediately trigger - price moved past the requested stop/target before it could be placed.';
      case -2019:
        return 'Margin is insufficient for this order.';
      case -2022:
        return 'ReduceOnly order rejected - the position was likely already closed.';
      default:
        return 'Exchange rejected the request.';
    }
  }

  @override
  Widget build(BuildContext context) {
    final code = (error['code'] as num).toInt();
    final symbol = error['symbol']?.toString();
    final time = error['time']?.toString();
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.m - 2),
      decoration: BoxDecoration(
        color: context.palette.warning.withOpacity(0.14),
        borderRadius: BorderRadius.circular(AppSpacing.radiusSmall + 2),
        border: Border.all(color: context.palette.warning.withOpacity(0.5)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.error_outline, color: context.palette.warning, size: 16),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Binance error $code${symbol != null ? ' ($symbol)' : ''}${time != null ? ' - $time' : ''}',
                  style: AppTypography.metadata.copyWith(color: context.palette.warning, fontSize: 11.5, fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 2),
                Text(_describe(code), style: AppTypography.metadata.copyWith(color: context.palette.textSecondary, fontSize: 11.5)),
              ],
            ),
          ),
          InkWell(
            onTap: onDismiss,
            child: Padding(
              padding: const EdgeInsets.all(2),
              child: Icon(Icons.close, size: 16, color: context.palette.textMuted),
            ),
          ),
        ],
      ),
    );
  }
}

Color _diagColor(BuildContext context, DiagLevel l) {
  switch (l) {
    case DiagLevel.ok:
      return context.palette.profit;
    case DiagLevel.warn:
      return context.palette.warning;
    case DiagLevel.bad:
      return context.palette.loss;
    case DiagLevel.unknown:
      return context.palette.textMuted;
  }
}

/// Part 24: 6 dots in one row (backend, socket, data, scan, strategy, orders). Visible even when the card is collapsed.
class _HealthStrip extends StatelessWidget {
  final DiagStatus diag;
  const _HealthStrip({required this.diag});

  static const Map<String, String> _short = {
    'backend': 'Backend',
    'ws': 'Socket',
    'market_data': 'Data',
    'scanner': 'Scan',
    'strategy': 'Strategy',
    'execution': 'Orders',
  };

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        for (final i in diag.items)
          Expanded(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 10,
                  height: 10,
                  decoration: BoxDecoration(color: _diagColor(context, i.level), shape: BoxShape.circle),
                ),
                const SizedBox(height: 3),
                Text(
                  _short[i.key] ?? i.title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTypography.metadata.copyWith(color: context.palette.textSecondary, fontSize: 10),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

/// Part 24: one plain line per check (shown when the card is opened).
class _HealthDetail extends StatelessWidget {
  final DiagStatus diag;
  const _HealthDetail({required this.diag});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        for (final i in diag.items)
          Padding(
            padding: const EdgeInsets.only(bottom: 4),
            child: Row(
              children: [
                Container(
                  width: 8,
                  height: 8,
                  decoration: BoxDecoration(color: _diagColor(context, i.level), shape: BoxShape.circle),
                ),
                const SizedBox(width: 8),
                Text(
                  i.title,
                  style: AppTypography.metadata.copyWith(color: context.palette.textPrimary, fontSize: 12, fontWeight: FontWeight.w600),
                ),
                const Spacer(),
                Flexible(
                  child: Text(
                    i.detail,
                    textAlign: TextAlign.right,
                    overflow: TextOverflow.ellipsis,
                    style: AppTypography.metadata.copyWith(color: _diagColor(context, i.level), fontSize: 12),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}
