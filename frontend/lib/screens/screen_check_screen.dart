import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';

/// Part 75 (Screenshot Check 2 of 2): the Screenshot Check on a screen. Read-only: it asks the backend for /api/v2/screen_check (Part 74) for ONE coin and ONE time, draws the answer and changes nothing
/// (no setting, no order, no file). The screenshot itself is NOT read: you only type the coin (like BTCUSDT) and, if you want, the time in UTC (like 2026-10-31 14:30); empty time = the newest candle.
/// Two blocks, never mixed: EVIDENCE (the 2 indicators at that candle + how this coin behaved in the same state before, with sample count and label) and OPINION (words only, always labelled, never an order).
/// Under 30 similar candles the screen shows "NOT ENOUGH DATA" and no percentage. Dart NOT compiled (the owner's APK build is the proof).
class ScreenCheckScreen extends StatefulWidget {
  const ScreenCheckScreen({super.key});

  @override
  State<ScreenCheckScreen> createState() => _ScreenCheckScreenState();
}

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<dynamic> _l(Object? v) => v is List ? v : const [];
String _t(Object? v) => (v == null || '$v'.trim().isEmpty) ? '--' : '$v';
String _n(Object? v, [int d = 4]) => v is num ? v.toStringAsFixed(d) : '--';
int _int(Object? v) => v is num ? v.toInt() : 0;

String _problem(Map<String, dynamic> r) {
  switch (r['state']) {
    case 'off':
      return 'The V2 data API is off. In the owl_data folder make a file named v2_api_enabled that contains 1, then try again.';
    case 'old':
      return r['code'] == 400
          ? 'The coin must look like BTCUSDT and the time like 2026-10-31 14:30 (UTC), or leave the time empty.'
          : 'This backend does not have the Screenshot Check route yet. Install the newest zip, restart the backend, then try again.';
    default:
      return 'Cannot reach the backend right now. Try again.';
  }
}

class _ScreenCheckScreenState extends State<ScreenCheckScreen> {
  final _sym = TextEditingController(text: 'BTCUSDT');
  final _at = TextEditingController();
  String _iv = '5m';
  Map<String, dynamic>? _data;
  bool _loading = false;

  @override
  void dispose() {
    _sym.dispose();
    _at.dispose();
    super.dispose();
  }

  Future<void> _go() async {
    FocusScope.of(context).unfocus();
    setState(() => _loading = true);
    final d = await context.read<AppProvider>().fetchScreenCheck(_sym.text.trim().toUpperCase(), _iv, _at.text.trim());
    if (!mounted) return;
    setState(() {
      _data = d;
      _loading = false;
    });
  }

  Widget _chip(String text, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
        decoration: BoxDecoration(color: c.withOpacity(0.12), borderRadius: BorderRadius.circular(6), border: Border.all(color: c.withOpacity(0.45))),
        child: Text(text, style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w800, color: c)),
      );

  Widget _line(AppPalette p, String k, String v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 1.5),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 118, child: Text(k, style: TextStyle(fontSize: 12, color: p.textSecondary))),
          Expanded(child: Text(v, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: p.textPrimary))),
        ]),
      );

  Widget _form(AppPalette p) => OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Which coin and when? (the picture is not read)', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
          const SizedBox(height: 8),
          TextField(controller: _sym, textCapitalization: TextCapitalization.characters, decoration: const InputDecoration(labelText: 'Coin, like BTCUSDT', isDense: true, border: OutlineInputBorder())),
          const SizedBox(height: 8),
          TextField(controller: _at, decoration: const InputDecoration(labelText: 'Time in UTC, like 2026-10-31 14:30 (empty = newest)', isDense: true, border: OutlineInputBorder())),
          const SizedBox(height: 8),
          Row(children: [
            for (final iv in const ['5m', '3m'])
              Padding(padding: const EdgeInsets.only(right: 6), child: ChoiceChip(label: Text(iv), selected: _iv == iv, onSelected: (_) => setState(() => _iv = iv))),
            const Spacer(),
            FilledButton(onPressed: _loading ? null : _go, child: const Text('Check')),
          ]),
        ]),
      );

  Widget _evidence(AppPalette p, Map<String, dynamic> r) {
    final st = _m(r['state']);
    final ev = _m(r['evidence']);
    final pct = _m(ev['pct']);
    final recent = _l(r['recent']).whereType<Map>().map((e) => _m(e)).toList();
    final ok = r['status'] == 'OK';
    return OWLCard(
      edge: ok ? p.accent : p.warning,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('EVIDENCE  ${_t(r['symbol'])} ${_t(r['interval'])}', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary))),
          _chip(_t(r['status']), ok ? p.profit : p.warning),
        ]),
        Text('candle ${_t(r['candle_utc'])} UTC (asked ${_t(r['asked_at_utc'])}), ${_t(r['candles_read'])} candles read', style: TextStyle(fontSize: 11.5, color: p.textMuted)),
        if (r['note'] != null) Text('${r['note']}', style: TextStyle(fontSize: 12, color: p.warning)),
        if (st.isNotEmpty) ...[
          const SizedBox(height: 6),
          _line(p, 'Close', _n(st['close'], 6)),
          _line(p, 'EMA50', '${_n(st['ema50'], 6)}  (price ${_t(st['price_vs_ema'])}, ${_n(r['ema_distance_pct'], 2)} %)'),
          _line(p, 'SD zone', _t(st['band_zone'])),
          _line(p, 'TSI', '${_n(st['tsi'], 2)} vs signal ${_n(st['tsi_signal'], 2)}  (${_t(st['tsi_vs_signal'])}, zone ${_t(st['tsi_zone'])})'),
          _line(p, 'Z-score', '${_n(st['z'], 2)} vs Z-SMA ${_n(st['z_sma'], 2)}  (${_t(st['z_vs_sma'])})'),
          if (!ok) Text('only ${_t(r['candles_in_run_before'])} candles before this one, all numbers need ${_t(r['candles_needed_for_all_numbers'])}', style: TextStyle(fontSize: 11.5, color: p.warning)),
        ],
        if (ev.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text('Same state before, this coin only', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: p.textPrimary)),
          _line(p, 'Similar candles', '${_int(ev['similar_candles'])}'),
          if (pct.isNotEmpty) _line(p, 'Close 12 later', 'UP ${_n(pct['UP'], 1)} %   DOWN ${_n(pct['DOWN'], 1)} %   FLAT ${_n(pct['FLAT'], 1)} %'),
          Text(_t(ev['label']), style: TextStyle(fontSize: 11.5, color: pct.isEmpty ? p.warning : p.textSecondary)),
          if (ev['note'] != null) Text('${ev['note']}', style: TextStyle(fontSize: 11, color: p.textMuted)),
        ],
        if (recent.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text('Last candles (UTC)', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: p.textPrimary)),
          Text(recent.reversed.take(8).map((e) => '${e['t']} ${_n(e['chg_pct'], 2)}%').join('   '), style: TextStyle(fontSize: 11.5, color: p.textSecondary)),
        ],
      ]),
    );
  }

  Widget _opinion(AppPalette p, Map<String, dynamic> o) {
    if (o.isEmpty) return const SizedBox.shrink();
    return OWLCard(
      edge: p.purple,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('OPINION', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary))),
          _chip('NOT PROOF, NOT AN ORDER', p.purple),
        ]),
        const SizedBox(height: 4),
        Text(_t(o['stance']), style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary)),
        for (final x in _l(o['reasons'])) Text('- $x', style: TextStyle(fontSize: 12, color: p.textSecondary)),
        if (_l(o['scenarios']).isNotEmpty) ...[
          const SizedBox(height: 6),
          Text('Scenarios', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: p.textPrimary)),
          for (final x in _l(o['scenarios'])) Text('- $x', style: TextStyle(fontSize: 12, color: p.textSecondary)),
        ],
        const SizedBox(height: 6),
        Text('Probability', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: p.textPrimary)),
        Text(_t(o['probability']), style: TextStyle(fontSize: 12, color: p.textPrimary)),
        const SizedBox(height: 6),
        Text(_t(o['label']), style: TextStyle(fontSize: 11, color: p.textMuted)),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _data;
    final List<Widget> kids = [_form(p)];
    if (_loading) {
      kids.add(const Padding(padding: EdgeInsets.only(top: 40), child: Center(child: CircularProgressIndicator())));
    } else if (d != null) {
      if (d['status'] == null) {
        kids.add(OWLCard(edge: p.warning, child: Text(d['ready'] == false ? _t(d['note']) : _problem(d), style: TextStyle(fontSize: 13, color: p.textPrimary))));
      } else {
        kids.addAll([_evidence(p, d), _opinion(p, _m(d['opinion']))]);
      }
    }
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.l, AppSpacing.l, AppSpacing.xl),
      children: [for (final w in kids) Padding(padding: const EdgeInsets.only(bottom: AppSpacing.m), child: w)],
    );
  }
}
