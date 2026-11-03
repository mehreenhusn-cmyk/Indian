import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/load_state.dart';
import '../widgets/owl_card.dart';

/// Part 35 (FILE 30): the SMALL ACCOUNT card of the Sniper. Read only, paper only: it never opens, closes or changes anything.
/// It asks GET /api/v2/sniper_capital (Part 34) and shows: today's throttle (STOP / SLOW / PUSH / NORMAL with one plain line and how many trades are left),
/// what ONE trade may look like at this capital, the growth plan, and the daily / weekly view. Every number comes from the backend; nothing is worked out here.
/// The money numbers are a REPLAY of the saved paper results (in R) at this capital: the card says so. Below 30 trades / 3 days the plan shows NO number.
/// One book per card (LEARN or REAL paper trades), never added. LoadSpinner (Part 1) while it waits. Use: CapitalCard(capital: 10).
/// Dart NOT compiled (the APK build is the proof).

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> _l(Object? v) => v is List ? [for (final e in v) _m(e)] : <Map<String, dynamic>>[];
double _d(Object? v) => v is num ? v.toDouble() : 0.0;
String _r(Object? v) => '${_d(v) >= 0 ? '+' : ''}${_d(v).toStringAsFixed(2)} R';
String _usdt(Object? v) => '${_d(v) >= 0 ? '+' : ''}${_d(v).toStringAsFixed(2)}';

class CapitalCard extends StatefulWidget {
  final double capital;
  final double risk;
  const CapitalCard({super.key, this.capital = 10, this.risk = 1});

  @override
  State<CapitalCard> createState() => _CapitalCardState();
}

class _CapitalCardState extends State<CapitalCard> {
  Map<String, dynamic>? _data;
  bool _busy = true;
  String _book = 'learn';

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(CapitalCard old) {
    super.didUpdateWidget(old);
    if (old.capital != widget.capital || old.risk != widget.risk) _load();
  }

  Future<void> _load() async {
    setState(() => _busy = true);
    final d = await context.read<AppProvider>().fetchSniperCapital(capital: widget.capital, risk: widget.risk, book: _book);
    if (!mounted) return;
    setState(() {
      _data = d;
      _busy = false;
    });
  }

  Widget _chip(String text, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(color: c.withOpacity(0.15), borderRadius: BorderRadius.circular(20)),
        child: Text(text, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: c)),
      );

  Widget _title(AppPalette p, {Widget? tag}) => Row(children: [
        Expanded(child: Text('Small account (paper)', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary))),
        if (tag != null) tag,
      ]);

  Widget _line(AppPalette p, String t, {Color? c, double size = 12}) =>
      Padding(padding: const EdgeInsets.only(top: 6), child: Text(t, style: TextStyle(fontSize: size, color: c ?? p.textSecondary)));

  Widget _books(AppPalette p) => Padding(
        padding: const EdgeInsets.only(top: 8),
        child: Wrap(spacing: 8, children: [
          for (final b in const ['learn', 'real'])
            ChoiceChip(
              label: Text(b == 'learn' ? 'LEARN trades' : 'REAL-gate trades', style: const TextStyle(fontSize: 12)),
              selected: _book == b,
              onSelected: (_) {
                if (_book == b) return;
                _book = b;
                _load();
              },
            ),
        ]),
      );

  Widget _note(AppPalette p, String text, {Color? edge, String? chip}) => OWLCard(
        edge: edge,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(p, tag: chip == null ? null : _chip(chip, edge ?? p.textMuted)),
          _line(p, text, c: p.textPrimary),
        ]),
      );

  Widget _row(AppPalette p, String a, String b, String c, String d, {bool head = false}) {
    final st = TextStyle(fontSize: 11.5, fontWeight: head ? FontWeight.w800 : FontWeight.w500, color: head ? p.textMuted : p.textPrimary);
    return Padding(
      padding: const EdgeInsets.only(top: 4),
      child: Row(children: [
        Expanded(flex: 3, child: Text(a, style: st)),
        Expanded(flex: 2, child: Text(b, style: st)),
        Expanded(flex: 2, child: Text(c, style: st)),
        Expanded(flex: 3, child: Text(d, style: st, textAlign: TextAlign.right)),
      ]),
    );
  }

  Color _levelColor(AppPalette p, String lv) => lv == 'STOP' ? p.loss : (lv == 'SLOW' ? p.warning : (lv == 'PUSH' ? p.profit : p.textSecondary));

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _data;
    if (_busy || d == null) return OWLCard(child: Column(children: [_title(p), LoadSpinner(onRetry: _load)]));
    final st = '${d['state']}';
    if (st == 'off') return _note(p, 'The V2 data API or the Sniper is switched off, so the small account view cannot be read.', edge: p.textMuted, chip: 'OFF');
    if (st == 'old') return _note(p, 'This backend has no small account route yet. Install the newest backend zip and restart the backend.', edge: p.warning, chip: 'OLD BACKEND');
    if (st == 'error') return _note(p, '${d['text'] ?? 'The small account view could not be read.'} Open the page again to retry.', edge: p.loss, chip: 'ERROR');
    final rep = _m(d['report']);
    final th = _m(rep['throttle']);
    final plan = _m(rep['plan']);
    final one = _m(d['one_trade']);
    final lv = '${th['level'] ?? 'NORMAL'}';
    final c = _levelColor(p, lv);
    final daily = _l(rep['daily']);
    final weekly = _l(rep['weekly']);
    final shown = daily.length > 7 ? daily.sublist(daily.length - 7) : daily;
    final n = _d(d['n_trades']).toInt();
    return OWLCard(
      edge: c,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, tag: _chip('TODAY: $lv', c)),
        _books(p),
        _line(p, '${th['text'] ?? ''}', c: p.textPrimary, size: 13),
        if (th['new_trades_left'] != null) _line(p, 'New trades left today: ${_d(th['new_trades_left']).toInt()}. Today ${_r(th['net_r'])}, ${_d(th['trades_today']).toInt()} trades.', size: 11.5),
        const Divider(height: 22),
        Text('Growth plan', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: p.textPrimary)),
        if ('${plan['state']}' == 'NOT_ENOUGH_DATA') ...[
          _line(p, '$n trades on ${_d(plan['days']).toInt()} days so far (needs 30 trades on 3 days).', c: p.textPrimary),
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(6),
              child: LinearProgressIndicator(value: (n / 30).clamp(0.0, 1.0), minHeight: 8, backgroundColor: p.border, color: p.accent),
            ),
          ),
          _line(p, 'No growth number is shown until then. A guess would be a fake number.', size: 11.5, c: p.textMuted),
        ] else
          for (final t in (plan['lines'] is List ? plan['lines'] as List : const <Object?>[])) _line(p, '$t', size: 11.5),
        const Divider(height: 22),
        Text('One trade at ${_d(d['capital']).toStringAsFixed(0)} USDT', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: p.textPrimary)),
        _line(p, '${one['text'] ?? ''}', c: '${one['state']}' == 'OK' ? p.textPrimary : p.warning, size: 11.5),
        if (shown.isNotEmpty) ...[
          const Divider(height: 22),
          Text('Last days (replay)', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: p.textPrimary)),
          _row(p, 'Day', 'Trades', 'Wins', 'Net / capital', head: true),
          for (final r in shown) _row(p, '${r['day']}'.substring(5), '${_d(r['trades']).toInt()}', '${_d(r['win_pct']).toStringAsFixed(0)}%', '${_r(r['net_r'])}  ${_d(r['capital_end']).toStringAsFixed(2)}'),
        ],
        if (weekly.isNotEmpty)
          Theme(
            data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
            child: ExpansionTile(
              tilePadding: EdgeInsets.zero,
              childrenPadding: EdgeInsets.zero,
              title: Text('Weekly view (${weekly.length})', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: p.textSecondary)),
              children: [
                _row(p, 'Week', 'Trades', 'Wins', 'USDT / capital', head: true),
                for (final w in weekly) _row(p, '${w['week']}', '${_d(w['trades']).toInt()}', '${_d(w['win_pct']).toStringAsFixed(0)}%', '${_usdt(w['net_usdt'])}  ${_d(w['capital_end']).toStringAsFixed(2)}'),
              ],
            ),
          ),
        _line(p, 'Book: ${_book == 'learn' ? 'LEARN' : 'REAL-gate'} paper trades only. Money numbers replay the saved results in R at this capital (simulated). Paper only, a guide, not a promise.', size: 11, c: p.textMuted),
      ]),
    );
  }
}
