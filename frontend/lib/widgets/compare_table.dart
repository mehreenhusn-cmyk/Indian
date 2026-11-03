import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import 'owl_card.dart';

/// Part 40 (FILE 48): the ONE shared comparison table. Pure display: no network, no provider, no state.
/// Rows = the separate books (Main bot, Dual Bot paper, Brain, Sniper, Replay). Same columns for every row: Trades, Won, Net USDT.
/// Every row says its OWN period in small text, so nobody reads a 'today' number next to a '7 days' number by mistake.
/// The books are NEVER added together: there is no total row on purpose. A missing number prints '--' (never 0, never a guess).
/// A row that could not be loaded prints its reason in one small line instead of numbers. Dart NOT compiled.

/// One book = one row. [state]: 'ok' (numbers are real), 'wait' (still loading), 'off' (route off / old backend), 'error', 'empty' (no closed trade in the period).
class CompareRow {
  final String book; // 'Main bot', 'Dual Bot paper', 'Brain', 'Sniper LEARN', 'Sniper Replay'
  final String sub; // one short line: what this book is ('paper, all coins', 'replay on unseen days')
  final String period; // 'Today (from 5:30 AM IST)', 'All LEARN trades', 'Last 7 test days'
  final int? trades; // closed trades in the period, null = not known
  final int? wins; // winning closed trades, null = not known
  final double? net; // net USDT in the period, null = not known
  final String state;
  final String note; // reason line for wait / off / error / empty, or a caveat for ok
  final bool simulated; // true for replays: money is simulated, row gets a small 'simulated' tag

  const CompareRow({
    required this.book,
    this.sub = '',
    this.period = '',
    this.trades,
    this.wins,
    this.net,
    this.state = 'ok',
    this.note = '',
    this.simulated = false,
  });

  /// Won % only when both numbers are real and at least one trade closed.
  double? get winPct => (trades != null && wins != null && trades! > 0) ? wins! * 100.0 / trades! : null;
  bool get hasNumbers => state == 'ok' && (trades != null || net != null);
}

String _sg(double? v) => v == null ? '--' : '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}';

class CompareTable extends StatelessWidget {
  final String title;
  final List<CompareRow> rows;
  final String footer; // optional extra line under the table (e.g. which route is off)
  final VoidCallback? onRetry;

  const CompareTable({super.key, this.title = 'Books side by side', required this.rows, this.footer = '', this.onRetry});

  /// True when every row that has numbers uses the same period text. The caller never has to guess.
  bool get samePeriod {
    final ps = {for (final r in rows) if (r.hasNumbers && r.period.isNotEmpty) r.period};
    return ps.length <= 1;
  }

  Widget _head(AppPalette p, String t, {bool left = false}) => Text(t,
      textAlign: left ? TextAlign.left : TextAlign.right, style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w700, color: p.textMuted));

  Widget _cell(AppPalette p, String t, {Color? c, bool bold = false}) => Text(t,
      textAlign: TextAlign.right, maxLines: 1, style: TextStyle(fontSize: 13, fontWeight: bold ? FontWeight.w800 : FontWeight.w600, color: c ?? p.textPrimary));

  Widget _row(AppPalette p, CompareRow r) {
    final ok = r.hasNumbers;
    final netC = r.net == null || r.net == 0 ? p.textPrimary : (r.net! > 0 ? p.profit : p.loss);
    final wp = r.winPct;
    final sub = [r.sub, r.period].where((e) => e.isNotEmpty).join('  |  ');
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
          Expanded(
            flex: 5,
            child: Row(children: [
              Flexible(child: Text(r.book, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary))),
              if (r.simulated)
                Container(
                  margin: const EdgeInsets.only(left: 6),
                  padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
                  decoration: BoxDecoration(color: p.warning.withOpacity(0.15), borderRadius: BorderRadius.circular(8)),
                  child: Text('simulated', style: TextStyle(fontSize: 9.5, fontWeight: FontWeight.w700, color: p.warning)),
                ),
            ]),
          ),
          Expanded(flex: 2, child: _cell(p, ok && r.trades != null ? '${r.trades}' : '--')),
          Expanded(flex: 2, child: _cell(p, ok && wp != null ? '${wp.toStringAsFixed(0)}%' : '--')),
          Expanded(flex: 3, child: _cell(p, ok ? _sg(r.net) : '--', c: ok ? netC : p.textMuted, bold: true)),
        ]),
        if (sub.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 1), child: Text(sub, style: TextStyle(fontSize: 10.5, color: p.textMuted))),
        if (r.note.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 1), child: Text(r.note, style: TextStyle(fontSize: 10.5, color: r.state == 'error' ? p.loss : p.textSecondary))),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final differ = !samePeriod;
    return OWLCard(
      edge: differ ? p.warning : null,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(title, style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary))),
          if (onRetry != null) InkWell(onTap: onRetry, child: Padding(padding: const EdgeInsets.all(4), child: Icon(Icons.refresh_rounded, size: 18, color: p.textMuted))),
        ]),
        const SizedBox(height: 8),
        Row(children: [
          Expanded(flex: 5, child: _head(p, 'Book', left: true)),
          Expanded(flex: 2, child: _head(p, 'Trades')),
          Expanded(flex: 2, child: _head(p, 'Won')),
          Expanded(flex: 3, child: _head(p, 'Net USDT')),
        ]),
        Divider(height: 10, color: p.border),
        if (rows.isEmpty) Text('No book to show yet.', style: TextStyle(fontSize: 12, color: p.textMuted)),
        for (final r in rows) _row(p, r),
        const SizedBox(height: 10),
        if (differ)
          Text('The periods are NOT the same (see the small line under each book). Compare with care.',
              style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: p.warning)),
        Text('Separate books. Never added together, so there is no total row. A missing number shows --.', style: TextStyle(fontSize: 10.5, color: p.textMuted)),
        if (footer.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 2), child: Text(footer, style: TextStyle(fontSize: 10.5, color: p.textMuted))),
      ]),
    );
  }
}
