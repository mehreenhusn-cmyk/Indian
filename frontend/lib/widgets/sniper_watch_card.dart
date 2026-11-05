import 'package:flutter/material.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';
import 'owl_number.dart';
import 'owl_row.dart';
import 'owl_sentence.dart';

/// Part 16 (R33b): the WATCHLIST on the Sniper tab. Data = GET /api/v2/sniper_watch (Part 15): favourites + the fastest coins, one row per coin:
/// ARMED (a signal is on), NEAR (the two EMAs are close), WATCH (only moving). Flat list in ONE card (OwlListCard / OwlRow), a small pill on the right,
/// the 1 h move under it, ONE reason line under the symbol. Tap a row = sheet with the full reason, entry / stop / target (only when armed), mode and market state.
/// Watch only: no button here sends an order. "Armed" is NOT a promise (the win chance is unknown). Dart NOT compiled.
class SniperWatchCard extends StatefulWidget {
  final Map<String, dynamic>? w;

  const SniperWatchCard({super.key, required this.w});

  @override
  State<SniperWatchCard> createState() => _SniperWatchCardState();
}

class _SniperWatchCardState extends State<SniperWatchCard> {
  bool _all = false;
  bool _armedOnly = false;
  static const int _top = 5;

  double? _d(Object? v) => v is num ? v.toDouble() : null;

  /// "12 s ago", "5 min ago", "1 h 10 min ago" (over 60 minutes = hours + minutes).
  String _ago(Object? savedAt) {
    final t = _d(savedAt);
    if (t == null) return '';
    final s = (DateTime.now().millisecondsSinceEpoch / 1000 - t).round();
    if (s < 0 || s < 60) return '${s < 0 ? 0 : s} s ago';
    final m = s ~/ 60;
    if (m < 60) return '$m min ago';
    return '${m ~/ 60} h ${m % 60} min ago';
  }

  String _problem(String? st, Object? text) {
    switch (st) {
      case 'off':
        return text == null ? 'The Sniper is switched off.' : '$text';
      case 'old':
        return 'This backend has no watchlist yet. Install the newest backend zip and restart it.';
      case 'NO_DATA':
        return 'No saved candles yet for the watchlist coins. Try again in a few minutes.';
      case 'ERROR':
        return 'The scan failed. Pull down to try again.';
      default:
        return 'Cannot reach the backend right now. Pull down to try again.';
    }
  }

  String _pillText(Map<String, dynamic> r) {
    final side = '${r['side'] ?? ''}'.toUpperCase();
    return r['state'] == 'ARMED' ? (side.isEmpty ? 'ARMED' : 'ARMED $side') : '${r['state'] ?? 'WATCH'}';
  }

  String _tone(Map<String, dynamic> r) {
    if (r['state'] == 'NEAR') return 'warn';
    if (r['state'] != 'ARMED') return '';
    final s = '${r['side'] ?? ''}'.toUpperCase();
    if (s.contains('BUY') || s.contains('LONG')) return 'good';
    if (s.contains('SELL') || s.contains('SHORT')) return 'bad';
    return 'warn';
  }

  Widget _chip(BuildContext context, String t, bool on, VoidCallback f) {
    final p = context.palette;
    return GestureDetector(
      onTap: f,
      behavior: HitTestBehavior.opaque,
      child: Padding(
        padding: const EdgeInsets.only(left: AppSpacing.m, top: 4, bottom: 4),
        child: Text(t, style: context.type.metadata.copyWith(fontWeight: FontWeight.w700, color: on ? p.textPrimary : p.textMuted)),
      ),
    );
  }

  Widget _line(BuildContext context, String k, String v) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox(width: 110, child: Text(k, style: context.type.metadata)),
        Expanded(child: Text(v, style: context.type.primary.copyWith(color: p.textPrimary))),
      ]),
    );
  }

  void _open(BuildContext context, Map<String, dynamic> r) {
    final p = context.palette;
    final armed = r['state'] == 'ARMED';
    final m15 = _d(r['move_15m_pct']);
    final m1 = _d(r['move_1h_pct']);
    final mode = '${r['mode'] ?? '--'}${r['mode_learned'] == true ? '' : ' (default, not learned yet)'}';
    final age = r['age'];
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: p.surface,
      isScrollControlled: true,
      builder: (_) => SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(AppSpacing.l),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            Row(children: [
              Expanded(child: Text('${r['symbol'] ?? '--'}', style: context.type.section)),
              OwlPill(_pillText(r), tone: _tone(r)),
            ]),
            const SizedBox(height: AppSpacing.m),
            Text('${r['reason'] ?? ''}', style: context.type.secondary.copyWith(height: 1.35)),
            const SizedBox(height: AppSpacing.m),
            _line(context, 'Mode', mode),
            _line(context, 'Market', '${r['regime'] ?? '--'}'),
            _line(context, 'Price', fmtPrice(_d(r['price']))),
            _line(context, 'Move 15 m / 1 h', '${m15 == null ? '--' : '${fmtSigned(m15)}%'}  /  ${m1 == null ? '--' : '${fmtSigned(m1)}%'}'),
            if (armed) ...[
              _line(context, 'Signal age', age == 0 ? 'newest candle' : '$age candle${age == 1 ? '' : 's'} ago'),
              _line(context, 'Entry', fmtPrice(_d(r['entry_price']))),
              _line(context, 'Stop', '${fmtPrice(_d(r['stop_loss']))}${_d(r['stop_pct']) == null ? '' : '  (${_d(r['stop_pct'])!.toStringAsFixed(2)}%)'}'),
              _line(context, 'Target', fmtPrice(_d(r['take_profit']))),
              _line(context, 'Reward : risk', fmtRR(_d(r['rr']))),
            ],
            const SizedBox(height: AppSpacing.m),
            Text('Watch only. Armed is not a promise: the win chance is unknown. Paper mode, no order is sent from here.', style: context.type.metadata),
          ]),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final w = widget.w;
    if (w == null) {
      return Column(crossAxisAlignment: CrossAxisAlignment.start, children: const [OwlSectionLabel('Watchlist'), OwlRowSkeleton(rows: 3)]);
    }
    if (w['state'] != 'OK') {
      return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const OwlSectionLabel('Watchlist'),
        Text(_problem('${w['state']}', w['text']), style: context.type.secondary),
      ]);
    }
    final all = <Map<String, dynamic>>[
      for (final e in (w['rows'] is List ? w['rows'] as List : const [])) if (e is Map) Map<String, dynamic>.from(e),
    ];
    final rows = _armedOnly ? all.where((r) => r['armed'] == true).toList() : all;
    final shown = _all || rows.length <= _top ? rows : rows.sublist(0, _top);
    final ago = _ago(w['saved_at']);
    final note = '${w['armed_n'] ?? 0} armed, ${w['near_n'] ?? 0} near${ago.isEmpty ? '' : ', scanned $ago'}';
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      OwlSectionLabel('Watchlist', note: note),
      Align(
        alignment: Alignment.centerRight,
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          _chip(context, 'All', !_armedOnly, () => setState(() => _armedOnly = false)),
          _chip(context, 'Armed only', _armedOnly, () => setState(() => _armedOnly = true)),
        ]),
      ),
      const SizedBox(height: 4),
      if (rows.isEmpty)
        Text(_armedOnly ? 'Nothing is armed right now. That is normal: the list waits for a real signal.' : 'No coins on the list yet. Add favourites in Market Watch.', style: context.type.secondary)
      else
        OwlListCard(children: [
          for (final r in shown)
            OwlRow(
              title: '${r['symbol'] ?? '--'}',
              sub: '${r['reason'] ?? ''}',
              onTap: () => _open(context, r),
              trailing: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.end, children: [
                OwlPill(_pillText(r), tone: _tone(r)),
                const SizedBox(height: 4),
                OwlNumber(_d(r['move_1h_pct']), suffix: '%', size: 13, alignRight: true),
              ]),
            ),
        ]),
      if (rows.length > _top)
        GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: () => setState(() => _all = !_all),
          child: Padding(
            padding: const EdgeInsets.only(top: AppSpacing.s),
            child: Text(_all ? 'Show less' : 'Show all ${rows.length}', style: context.type.metadata.copyWith(fontWeight: FontWeight.w700, color: context.palette.accent)),
          ),
        ),
    ]);
  }
}
