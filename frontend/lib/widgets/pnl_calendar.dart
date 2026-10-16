import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import 'glass_card.dart';

/// Daily P&L calendar (Binance "PNL Analysis" style), shown under the equity curve.
///
/// Draws only what the backend sends (`/api/calendar`): closed trades, after fee, grouped by the
/// same 5:30 AM IST trading day as the Dashboard "Today" ring - so a day here equals what the
/// ring showed that day. Nothing is calculated on the phone except colour strength.
/// Tap a day to see its trades, wins/losses and win rate right under the grid.
class PnlCalendar extends StatefulWidget {
  /// Response of GET /api/calendar (null while the first load is running).
  final Map<String, dynamic>? data;
  final ValueChanged<String> onMonthChanged;

  const PnlCalendar({super.key, required this.data, required this.onMonthChanged});

  @override
  State<PnlCalendar> createState() => _PnlCalendarState();
}

class _PnlCalendarState extends State<PnlCalendar> {
  String? _picked; // "YYYY-MM-DD" of the tapped day

  static const _months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  static const _dow = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];

  double _n(dynamic v) => v is num ? v.toDouble() : 0.0;
  int _i(dynamic v) => v is num ? v.toInt() : 0;

  String _signed(double v) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}';

  /// Short number for a small cell: 2 decimals under 100, 1 decimal under 1000, then "1.9k".
  String _cell(double v) {
    final a = v.abs();
    final sign = v < 0 ? '-' : '';
    if (a >= 1000) return '$sign${(a / 1000).toStringAsFixed(1)}k';
    if (a >= 100) return '$sign${a.toStringAsFixed(1)}';
    return '$sign${a.toStringAsFixed(2)}';
  }

  /// "2026-10" moved by [delta] months.
  String _shift(String ym, int delta) {
    final y = int.parse(ym.substring(0, 4));
    final m = int.parse(ym.substring(5, 7));
    final t = y * 12 + (m - 1) + delta;
    return '${t ~/ 12}-${(t % 12 + 1).toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = widget.data;

    Widget shell(List<Widget> kids) => GlassCard(
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.l),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: kids),
          ),
        );

    final title = Text('Daily P&L',
        style: AppTypography.primaryData.copyWith(color: p.textPrimary, fontSize: 16, fontWeight: FontWeight.w700));

    if (d == null || d['month'] is! String || (d['month'] as String).length != 7) {
      return shell([
        title,
        const SizedBox(height: 8),
        Padding(
          padding: const EdgeInsets.symmetric(vertical: AppSpacing.xl),
          child: Center(child: Text('Loading calendar...', style: context.type.secondary.copyWith(color: p.textMuted))),
        ),
      ]);
    }

    final month = d['month'] as String;
    final today = (d['today'] ?? '').toString();
    final first = (d['first_month'] ?? month).toString();
    final y = int.parse(month.substring(0, 4));
    final mo = int.parse(month.substring(5, 7));
    final byDate = <String, Map<String, dynamic>>{};
    for (final r in (d['days'] as List? ?? const [])) {
      if (r is Map) byDate['${r['date']}'] = Map<String, dynamic>.from(r);
    }
    final monthPnl = _n(d['month_pnl']);
    final monthTrades = _i(d['month_trades']);
    final monthWins = _i(d['month_wins']);
    final winPct = monthTrades > 0 ? (monthWins * 100 / monthTrades).round() : 0;
    final monthColor = monthPnl > 0 ? p.profit : (monthPnl < 0 ? p.loss : p.textMuted);

    double maxAbs = 0;
    for (final r in byDate.values) {
      final a = _n(r['pnl']).abs();
      if (a > maxAbs) maxAbs = a;
    }

    final canPrev = month.compareTo(first) > 0;
    final canNext = today.length >= 7 && month.compareTo(today.substring(0, 7)) < 0;

    Widget arrow(IconData ic, bool on, String target) => InkResponse(
          onTap: on
              ? () {
                  setState(() => _picked = null);
                  widget.onMonthChanged(target);
                }
              : null,
          radius: 20,
          child: Padding(
            padding: const EdgeInsets.all(6),
            child: Icon(ic, size: 22, color: on ? p.textPrimary : p.textMuted.withOpacity(0.35)),
          ),
        );

    // ----- grid -----
    final lead = DateTime(y, mo, 1).weekday % 7; // Sunday-first like Binance
    final daysInMonth = DateTime(y, mo + 1, 0).day;
    final cells = <Widget>[];
    for (var i = 0; i < lead; i++) {
      cells.add(const SizedBox.shrink());
    }
    for (var day = 1; day <= daysInMonth; day++) {
      final key = '$month-${day.toString().padLeft(2, '0')}';
      final r = byDate[key];
      final isToday = key == today;
      final future = today.isNotEmpty && key.compareTo(today) > 0;
      final pnl = r == null ? 0.0 : _n(r['pnl']);
      final has = r != null && _i(r['trades']) > 0;
      final strength = (has && maxAbs > 0) ? (0.14 + 0.30 * (pnl.abs() / maxAbs)) : 0.0;
      final tint = !has ? null : (pnl >= 0 ? p.profit : p.loss).withOpacity(strength);
      final picked = _picked == key;
      cells.add(GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: has ? () => setState(() => _picked = picked ? null : key) : null,
        child: Container(
          margin: const EdgeInsets.all(2),
          decoration: BoxDecoration(
            color: tint ?? p.glassFill,
            borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
            border: Border.all(
              color: picked ? p.accent : (isToday ? p.accent.withOpacity(0.55) : Colors.transparent),
              width: picked ? 1.6 : 1,
            ),
          ),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text('$day',
                  style: AppTypography.metadata.copyWith(
                    fontSize: 11,
                    fontWeight: isToday ? FontWeight.w800 : FontWeight.w600,
                    color: future ? p.textMuted.withOpacity(0.4) : p.textSecondary,
                  )),
              const SizedBox(height: 2),
              if (has)
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 1),
                  child: FittedBox(
                    fit: BoxFit.scaleDown,
                    child: Text(_cell(pnl),
                        style: AppTypography.metadata.copyWith(
                            fontSize: 9.5, fontWeight: FontWeight.w700, color: pnl >= 0 ? p.profit : p.loss)),
                  ),
                )
              else
                Text(future ? '' : '-', style: AppTypography.metadata.copyWith(fontSize: 9.5, color: p.textMuted.withOpacity(0.5))),
            ],
          ),
        ),
      ));
    }

    // ----- picked day detail -----
    Widget detail = const SizedBox.shrink();
    final pd = _picked == null ? null : byDate[_picked!];
    if (pd != null) {
      final t = _i(pd['trades']);
      final w = _i(pd['wins']);
      final pnl = _n(pd['pnl']);
      final c = pnl >= 0 ? p.profit : p.loss;
      detail = Padding(
        padding: const EdgeInsets.only(top: 10),
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            color: c.withOpacity(0.08),
            borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
            border: Border.all(color: c.withOpacity(0.25)),
          ),
          child: Row(
            children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(_picked!, style: AppTypography.secondaryData.copyWith(color: p.textPrimary, fontWeight: FontWeight.w700, fontSize: 13)),
                  const SizedBox(height: 3),
                  Text('$t trades  ·  $w wins / ${t - w} losses  ·  win ${(w * 100 / t).round()}%',
                      style: AppTypography.metadata.copyWith(color: p.textMuted, fontSize: 11)),
                ]),
              ),
              Text('${_signed(pnl)} USDT', style: AppTypography.primaryData.copyWith(color: c, fontSize: 15, fontWeight: FontWeight.w800)),
            ],
          ),
        ),
      );
    }

    return shell([
      Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          title,
          Row(mainAxisSize: MainAxisSize.min, children: [
            arrow(Icons.chevron_left_rounded, canPrev, _shift(month, -1)),
            Text('${_months[mo - 1]} $y',
                style: AppTypography.secondaryData.copyWith(color: p.textPrimary, fontWeight: FontWeight.w700, fontSize: 13)),
            arrow(Icons.chevron_right_rounded, canNext, _shift(month, 1)),
          ]),
        ],
      ),
      const SizedBox(height: 6),
      Text(
        monthTrades > 0
            ? '${_signed(monthPnl)} USDT  ·  $monthTrades trades  ·  win $winPct%'
            : 'No closed trades this month',
        style: AppTypography.secondaryData.copyWith(color: monthColor, fontSize: 12.5, fontWeight: FontWeight.w700),
      ),
      const SizedBox(height: 10),
      Row(
        children: [
          for (final l in _dow)
            Expanded(
              child: Center(child: Text(l, style: AppTypography.metadata.copyWith(color: p.textMuted, fontSize: 10.5))),
            ),
        ],
      ),
      const SizedBox(height: 4),
      GridView.count(
        crossAxisCount: 7,
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        childAspectRatio: 0.92,
        children: cells,
      ),
      detail,
      const SizedBox(height: 6),
      Text('Closed trades, after fee. A day runs 5:30 AM to 5:30 AM IST, same as the Today ring.',
          style: AppTypography.metadata.copyWith(color: p.textMuted, fontSize: 10)),
    ]);
  }
}
