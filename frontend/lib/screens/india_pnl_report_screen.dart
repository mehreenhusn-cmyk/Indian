import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../services/india_api.dart';
import '../theme/app_theme.dart';
import '../widgets/india_ui.dart';
import '../widgets/owl_card.dart';

/// Trades tab: P&L report with date range / index filter, totals, equity curve,
/// day-wise table, top contracts and the full closed-trade list (+ copy CSV).
class IndiaTradesTab extends StatefulWidget {
  final IndiaApi api;
  final String clockIso; // backend (market) clock - "today" follows it, not the phone
  const IndiaTradesTab({super.key, required this.api, required this.clockIso});

  @override
  State<IndiaTradesTab> createState() => _IndiaTradesTabState();
}

class _IndiaTradesTabState extends State<IndiaTradesTab> {
  String _range = 'Today';
  String _under = 'All';
  Map<String, dynamic>? _rep;
  String? _error;
  bool _loading = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  /// Ranges are resolved by the backend on the market's own date, never on the phone's clock.
  String _query() {
    final q = <String>[];
    if (_range == 'Today') q.add('period=today');
    if (_range == '7D') q.add('period=7d');
    if (_range == '30D') q.add('period=30d');
    if (_under != 'All') q.add('underlying=$_under');
    return q.isEmpty ? '' : '?${q.join('&')}';
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final rep = Map<String, dynamic>.from(await widget.api.get('/report${_query()}') as Map);
      if (mounted) setState(() {
        _rep = rep;
        _error = null;
      });
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _copyCsv() async {
    try {
      final csv = await widget.api.getText('/trades.csv${_query()}');
      await Clipboard.setData(ClipboardData(text: csv));
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('CSV copied to clipboard')));
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Color _reasonColor(AppPalette p, String r) {
    if (r.startsWith('TP')) return p.profit;
    if (r.startsWith('SL') || r.startsWith('TSL') || r == 'ESL') return p.loss;
    return p.textSecondary;
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = context.type;
    final rep = _rep;
    final tot = Map<String, dynamic>.from((rep?['totals'] as Map?) ?? {});
    final net = nd(tot['net']);
    final eq = ((rep?['equity'] as List?) ?? []).map((e) => nd((e as Map)['equity'])).toList();
    final daily = ((rep?['daily'] as List?) ?? []).map((e) => Map<String, dynamic>.from(e as Map)).toList();
    final brk = ((rep?['breakdown'] as List?) ?? []).map((e) => Map<String, dynamic>.from(e as Map)).toList();
    final trades = ((rep?['trades'] as List?) ?? []).map((e) => Map<String, dynamic>.from(e as Map)).toList();

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(AppSpacing.l),
        children: [
          IChoice<String>(values: const ['Today', '7D', '30D', 'All'], current: _range, label: (v) => v == 'Today' ? 'Today' : (v == 'All' ? 'All time' : (v == '7D' ? '7 days' : '30 days')), onPick: (v) {
            setState(() => _range = v);
            _load();
          }),
          const SizedBox(height: 6),
          IChoice<String>(values: const ['All', 'NIFTY', 'BANKNIFTY', 'FINNIFTY'], current: _under, label: (v) => v == 'All' ? 'All indices' : v, onPick: (v) {
            setState(() => _under = v);
            _load();
          }),
          const SizedBox(height: AppSpacing.m),
          if (_error != null) Text(_error!, style: IT.small(context).copyWith(color: p.loss)),
          if (rep == null && _error == null) const Center(child: Padding(padding: EdgeInsets.all(24), child: CircularProgressIndicator())),
          if (rep != null) ...[
            ICard(
              tint: net > 0 ? p.profit.withOpacity(0.5) : (net < 0 ? p.loss.withOpacity(0.5) : null),
              padding: const EdgeInsets.all(14),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Net realised P&L (after charges)', style: IT.small(context)),
                FittedBox(fit: BoxFit.scaleDown, alignment: Alignment.centerLeft, child: Text(inr(net, sign: true), style: IT.big(context).copyWith(fontSize: 26, color: pnlColor(p, net)))),
                const SizedBox(height: AppSpacing.m),
                Row(children: [
                  IMetric('Gross', inr(nd(tot['gross']), sign: true), color: pnlColor(p, nd(tot['gross']))),
                  IMetric('Charges', inr(nd(tot['fees']))),
                  IMetric('Trades', '${tot['trades'] ?? 0}'),
                ]),
                const SizedBox(height: AppSpacing.m),
                Row(children: [
                  IMetric('Win rate', '${nd(tot['win_pct']).toStringAsFixed(1)}%'),
                  IMetric('Best', inr(nd(tot['best']), sign: true), color: p.profit),
                  IMetric('Worst', inr(nd(tot['worst']), sign: true), color: p.loss),
                ]),
                if (tot['profit_factor'] != null) ...[
                  const SizedBox(height: AppSpacing.m),
                  Row(children: [IMetric('Profit factor', '${tot['profit_factor']}'), const Spacer(), const Spacer()]),
                ],
              ]),
            ),
            const SizedBox(height: AppSpacing.m),
            if (eq.length >= 2) ...[
              const IHeading('EQUITY CURVE'),
              ICard(padding: const EdgeInsets.all(12), child: SparkLine(eq, eq.last >= eq.first ? p.profit : p.loss)),
              const SizedBox(height: AppSpacing.l),
            ],
            if (daily.isNotEmpty) ...[
              const IHeading('DAY-WISE'),
              ...daily.reversed.map((d) => Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: Row(children: [
                      Expanded(child: Text(dmy(d['date']), style: IT.body(context))),
                      Text('${d['trades']} trades  ·  ${d['wins']} wins', style: IT.small(context)),
                      const SizedBox(width: 12),
                      Text(inr(nd(d['net']), sign: true), style: IT.body(context).copyWith(fontWeight: FontWeight.w700, color: pnlColor(p, nd(d['net'])))),
                    ]),
                  )),
              const SizedBox(height: AppSpacing.l),
            ],
            if (brk.isNotEmpty) ...[
              const IHeading('TOP CONTRACTS'),
              ...brk.take(5).map((b) => Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: Row(children: [
                      Expanded(child: Text('${b['contract']}', style: IT.body(context))),
                      Text('${b['trades']}x', style: IT.small(context)),
                      const SizedBox(width: 12),
                      Text(inr(nd(b['net']), sign: true), style: IT.body(context).copyWith(fontWeight: FontWeight.w700, color: pnlColor(p, nd(b['net'])))),
                    ]),
                  )),
              const SizedBox(height: AppSpacing.l),
            ],
            IHeading('CLOSED TRADES (${trades.length})', trailing: TextButton(onPressed: _copyCsv, child: const Text('Copy CSV'))),
            if (trades.isEmpty) Text('No closed trades in this range.', style: IT.small(context)),
            ...trades.map((tr) => _tradeCard(p, t, tr)),
          ],
          if (_loading) const Padding(padding: EdgeInsets.only(top: 8), child: LinearProgressIndicator(minHeight: 2)),
          const SizedBox(height: AppSpacing.huge),
        ],
      ),
    );
  }

  Widget _tradeCard(AppPalette p, AppText t, Map<String, dynamic> tr) {
    final c = Map<String, dynamic>.from((tr['contract'] as Map?) ?? {});
    final pnl = nd(tr['pnl']);
    final side = '${tr['action']}' == 'LONG' ? 'CE' : 'PE';
    final reason = '${tr['reason']}';
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.s),
      child: ICard(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text('${tr['underlying']} ${c['strike']} $side', style: IT.body(context).copyWith(fontWeight: FontWeight.w700))),
            Text(inr(pnl, sign: true), style: IT.h(context).copyWith(color: pnlColor(p, pnl))),
          ]),
          const SizedBox(height: 4),
          Wrap(spacing: 6, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
            IPill(reason, _reasonColor(p, reason)),
            IPill('${tr['product']}', p.accent),
            if ('${tr['tag']}'.isNotEmpty) IPill('${tr['tag']}', p.warning),
            Text('qty ${tr['qty']}', style: IT.small(context)),
          ]),
          const SizedBox(height: 6),
          Text('${num2(nd(tr['entry_premium']))} → ${num2(nd(tr['exit_premium']))}   ·   spot ${num2(nd(tr['entry_spot']))} → ${num2(nd(tr['exit_spot']))}', style: IT.small(context)),
          Text('${dayTime(tr['opened_at'])} → ${dayTime(tr['closed_at'])}   ·   charges ${inr(nd(tr['fees']))}', style: IT.small(context)),
        ]),
      ),
    );
  }
}
