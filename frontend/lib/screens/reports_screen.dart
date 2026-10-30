import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';

/// Part 62 (Reports 2 of 3): the FEES + TAX report on a screen. Read-only: it only asks the backend for /api/v2/fees_tax (Part 61 report),
/// shows it and changes nothing (no setting, no position, no order). The 4 boxes are shown one under the other and are NEVER added together.
/// Tax = an estimate from the owner's own v2_tax_config.json, never advice. No tax config = the backend says "TAX NOT CALCULATED" and why.
/// Opened from More > Fees and tax report. Pull down to refresh.
class ReportsScreen extends StatefulWidget {
  const ReportsScreen({super.key});

  @override
  State<ReportsScreen> createState() => _ReportsScreenState();
}

class _ReportsScreenState extends State<ReportsScreen> {
  static const _boxes = <String, List<String>>{
    'real_live': ['Real live', 'Real money trades'],
    'live_estimated': ['Live (estimated)', 'Live trades the app had to estimate'],
    'paper_b1': ['Paper bot 1', 'Practice money, not real'],
    'paper_b2': ['Paper bot 2', 'Practice money, not real'],
  };

  Map<String, dynamic>? _data;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final d = await context.read<AppProvider>().fetchFeesTax();
    if (!mounted) return;
    setState(() {
      _data = d;
      _loading = false;
    });
  }

  Future<void> _refresh() async {
    setState(() => _loading = true);
    await _load();
  }

  static String _num(Object? v, {bool sign = false}) {
    final n = v is num ? v.toDouble() : 0.0;
    final s = n.abs().toStringAsFixed(2).replaceAllMapped(RegExp(r'(\d)(?=(\d{3})+\.)'), (m) => '${m[1]},');
    final pre = n < 0 ? '-' : (sign && n > 0 ? '+' : '');
    return '$pre$s';
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _data;
    final List<Widget> kids = [];
    if (_loading && d == null) {
      kids.add(const Padding(padding: EdgeInsets.only(top: 80), child: Center(child: CircularProgressIndicator())));
    } else if (d == null || d['boxes'] is! Map) {
      kids.add(_message(p, _problem(d?['state'])));
    } else {
      kids.add(Text('Made ${d['made_utc'] ?? '--'} (UTC). Read-only: nothing is changed here. The 4 boxes are never added together.',
          style: TextStyle(fontSize: 12, color: p.textMuted)));
      final boxes = d['boxes'] as Map;
      for (final k in _boxes.keys) {
        if (boxes[k] is Map) kids.add(_boxCard(p, k, Map<String, dynamic>.from(boxes[k] as Map)));
      }
      if (d['tax'] is Map) kids.add(_taxCard(p, Map<String, dynamic>.from(d['tax'] as Map)));
      final notes = d['notes'];
      if (notes is List) {
        for (final n in notes) {
          kids.add(Padding(padding: const EdgeInsets.only(top: 4), child: Text('- $n', style: TextStyle(fontSize: 11, color: p.textMuted))));
        }
      }
    }
    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.l, AppSpacing.l, AppSpacing.xl),
        children: [for (final w in kids) Padding(padding: const EdgeInsets.only(bottom: AppSpacing.m), child: w)],
      ),
    );
  }

  static String _problem(Object? state) {
    switch (state) {
      case 'off':
        return 'The V2 data API is off. In the owl_data folder make a file named v2_api_enabled that contains 1, then pull down to refresh.';
      case 'old':
        return 'This backend does not have the fees + tax report yet. Install the Part 62 zip, restart the backend, then pull down.';
      default:
        return 'Cannot reach the backend right now. Pull down to try again.';
    }
  }

  Widget _message(AppPalette p, String text) =>
      OWLCard(edge: p.warning, child: Text(text, style: TextStyle(fontSize: 13, color: p.textPrimary)));

  Widget _row(AppPalette p, String label, String value, {Color? color, bool bold = false}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(children: [
          Expanded(child: Text(label, style: TextStyle(fontSize: 13, color: p.textSecondary))),
          Text(value, style: TextStyle(fontSize: 13, fontWeight: bold ? FontWeight.w800 : FontWeight.w600, color: color ?? p.textPrimary)),
        ]),
      );

  Color _netColor(AppPalette p, Object? v) => v is num && v < 0 ? p.negative : (v is num && v > 0 ? p.positive : p.textPrimary);

  Widget _boxCard(AppPalette p, String key, Map<String, dynamic> b) {
    final t = Map<String, dynamic>.from((b['totals'] as Map?) ?? const {});
    final names = _boxes[key]!;
    final est = (t['fee_estimated_rows'] as num?)?.toInt() ?? 0;
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(names[0], style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary)),
        Text(names[1], style: TextStyle(fontSize: 11, color: p.textMuted)),
        const SizedBox(height: AppSpacing.s),
        _row(p, 'Trades', '${t['trades'] ?? 0}'),
        _row(p, 'Gross', '${_num(t['gross_usdt'], sign: true)} USDT'),
        _row(p, 'Fees', '${_num(t['fees_usdt'])} USDT'),
        _row(p, 'Net', '${_num(t['net_realized_usdt'], sign: true)} USDT', color: _netColor(p, t['net_realized_usdt']), bold: true),
        if (t['funding_usdt_shown_only'] != null) _row(p, 'Funding (not in net)', '${_num(t['funding_usdt_shown_only'], sign: true)} USDT'),
        if (est > 0) Text('Fee was estimated for $est old trades.', style: TextStyle(fontSize: 11, color: p.warning)),
        if (t['note'] != null) Text('${t['note']}', style: TextStyle(fontSize: 11, color: p.textMuted)),
        _periods(p, 'By financial year', b['by_financial_year']),
        _periods(p, 'By month (UTC)', b['by_month_utc']),
        if (b['tax'] is String) Text('Tax: ${b['tax']}', style: TextStyle(fontSize: 11, color: p.textMuted)),
      ]),
    );
  }

  Widget _periods(AppPalette p, String title, Object? raw) {
    if (raw is! Map || raw.isEmpty) return const SizedBox.shrink();
    final keys = raw.keys.map((e) => '$e').toList()..sort((a, b) => b.compareTo(a));
    return Theme(
      data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
      child: ExpansionTile(
        tilePadding: EdgeInsets.zero,
        childrenPadding: EdgeInsets.zero,
        title: Text('$title (${keys.length})', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: p.textSecondary)),
        children: [
          for (final k in keys)
            Builder(builder: (_) {
              final v = Map<String, dynamic>.from(raw[k] as Map);
              return _row(p, '$k  (${v['trades'] ?? 0} trades, fee ${_num(v['fees_usdt'])})', _num(v['net_realized_usdt'], sign: true),
                  color: _netColor(p, v['net_realized_usdt']));
            }),
        ],
      ),
    );
  }

  Widget _taxCard(AppPalette p, Map<String, dynamic> x) {
    final ok = x['state'] == 'ESTIMATE';
    final years = x['years'];
    return OWLCard(
      edge: ok ? null : p.warning,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Tax estimate (real live only)', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary)),
        const SizedBox(height: AppSpacing.s),
        Text('${x['state'] ?? '--'}', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: ok ? p.textPrimary : p.warning)),
        if (x['reason'] != null) Text('${x['reason']}', style: TextStyle(fontSize: 12, color: p.textSecondary)),
        if (ok) ...[
          Text('${x['jurisdiction_label'] ?? ''}, rate ${x['tax_rate_pct'] ?? '--'}%', style: TextStyle(fontSize: 12, color: p.textSecondary)),
          if (years is Map)
            for (final k in (years.keys.map((e) => '$e').toList()..sort((a, b) => b.compareTo(a))))
              Builder(builder: (_) {
                final y = Map<String, dynamic>.from(years[k] as Map);
                return Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    _row(p, 'Year $k net', '${_num(y['net_realized_usdt'], sign: true)} USDT', color: _netColor(p, y['net_realized_usdt'])),
                    _row(p, 'Tax estimate', '${_num(y['tax_estimate_usdt'])} USDT', bold: true),
                    Text('${y['data'] ?? ''}', style: TextStyle(fontSize: 11, color: p.textMuted)),
                  ]),
                );
              }),
          if (x['rule'] != null) Padding(padding: const EdgeInsets.only(top: 6), child: Text('${x['rule']}', style: TextStyle(fontSize: 11, color: p.textMuted))),
        ],
        const SizedBox(height: 4),
        Text('Estimate only, not tax advice.', style: TextStyle(fontSize: 11, color: p.textMuted)),
      ]),
    );
  }
}
