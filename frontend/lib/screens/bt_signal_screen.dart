import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/bt_mini_chart.dart';
import '../widgets/owl_card.dart';

/// Part 87a (Signal Detail): read-only. One coin NOW from /api/v2/brain_signal (Part 87): small chart (EMA50, SD middle, 2 SD bands, entry / stop / target when the Brain says OPEN),
/// the Brain's answer with its reason, WHAT THE BRAIN SAW (chart sentences), WHY NOT EARLIER (its older answers), EVIDENCE FROM SIMILAR TRADES (under 30 closed trades = NOT ENOUGH DATA, no win rate)
/// and a DATA TO BRAIN panel. There is no ENTER button: paper trades open by themselves when the rule says OPEN, LIVE is locked. Dart NOT compiled (the APK build is the proof).
class BtSignalScreen extends StatefulWidget {
  final String symbol;
  final String interval;
  const BtSignalScreen({super.key, required this.symbol, this.interval = '5m'});

  static Future<void> open(BuildContext context, String symbol, [String interval = '5m']) =>
      Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => BtSignalScreen(symbol: symbol, interval: interval)));

  @override
  State<BtSignalScreen> createState() => _BtSignalScreenState();
}

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> _l(Object? v) => v is List ? [for (final e in v) _m(e)] : <Map<String, dynamic>>[];
List<String> _s(Object? v) => v is List ? [for (final e in v) '$e'] : <String>[];
double? _n(Object? v) => v is num ? v.toDouble() : null;

class _BtSignalScreenState extends State<BtSignalScreen> {
  Map<String, dynamic>? _r;
  bool _busy = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _busy = true);
    final r = await context.read<AppProvider>().fetchBrainSignal(widget.symbol, widget.interval);
    if (!mounted) return;
    setState(() {
      _r = r;
      _busy = false;
    });
  }

  String _problem(Map<String, dynamic> r) {
    switch (r['state']) {
      case 'off':
        return 'The V2 data API is off. Make the file v2_api_enabled (containing 1) in the owl_data folder, then pull down to refresh.';
      case 'old':
        return 'This backend does not have the Signal Detail route yet. Install the newest zip, restart the backend, then pull down.';
      default:
        return 'Cannot reach the backend right now. Pull down to try again.';
    }
  }

  Widget _title(AppPalette p, String t, [String? sub]) => Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(t, style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w800, color: p.textPrimary)),
          if (sub != null) Text(sub, style: TextStyle(fontSize: 11.5, color: p.textMuted)),
        ]),
      );

  Widget _chip(String t, Color c) => Container(
        margin: const EdgeInsets.only(right: 6, top: 4),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: c.withOpacity(0.14), borderRadius: BorderRadius.circular(8), border: Border.all(color: c.withOpacity(0.5))),
        child: Text(t, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: c)),
      );

  Widget _kv(AppPalette p, String k, String v, [Color? c]) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(children: [
          Expanded(child: Text(k, style: TextStyle(fontSize: 12.5, color: p.textSecondary))),
          Text(v, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: c ?? p.textPrimary)),
        ]),
      );

  String _px(double? v) => v == null ? '-' : (v >= 100 ? v.toStringAsFixed(2) : v.toStringAsFixed(v >= 1 ? 4 : 6));

  List<Widget> _body(AppPalette p, Map<String, dynamic> r) {
    final b = _m(r['brain']);
    final lv = r['levels'] == null ? null : _m(r['levels']);
    final ev = _m(r['evidence']);
    final dt = _m(r['data']);
    final dec = '${b['decision']}';
    final dc = dec.startsWith('OPEN') ? p.profit : (dec == 'WAIT' ? p.warning : p.textMuted);
    final lines = <BtLine>[];
    if (lv != null) {
      lines
        ..add(BtLine(_n(lv['entry']) ?? 0, 'ENTRY', p.textPrimary))
        ..add(BtLine(_n(lv['sl']) ?? 0, 'STOP', p.loss))
        ..add(BtLine(_n(lv['tp']) ?? 0, 'TARGET', p.profit));
    }
    final older = _l(r['why_not_earlier']);
    return [
      OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text('${r['symbol']}  ${r['interval']}', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: p.textPrimary))),
            Text(dec.replaceAll('_', ' '), style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: dc)),
          ]),
          Text('Candle closed ${r['candle_end']} - PAPER (pretend money)', style: TextStyle(fontSize: 11, color: p.textMuted)),
          Wrap(children: [_chip('${r['state']}', p.accent), _chip('${b['side']}', p.textSecondary)]),
          const SizedBox(height: 8),
          BtMiniChart(chart: _m(r['chart']), lines: lines, up: p.profit, down: p.loss, ema: p.accent, band: p.textMuted, text: p.textMuted),
          Text('Lines: EMA50 (colour), SD middle and 2 SD bands (grey).', style: TextStyle(fontSize: 10.5, color: p.textMuted)),
        ]),
      ),
      OWLCard(
        edge: dc,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(p, 'What the Brain says'),
          Text('${b['reason']}', style: TextStyle(fontSize: 13, color: p.textPrimary)),
          if (b['wait_for'] != null) ...[
            const SizedBox(height: 6),
            Text('Waiting for: ${b['wait_for']} (up to ${b['max_wait_candles']} candles, then the idea is dropped).', style: TextStyle(fontSize: 12.5, color: p.warning)),
          ],
          if (lv != null) ...[
            const SizedBox(height: 8),
            _kv(p, 'Entry', _px(_n(lv['entry']))),
            _kv(p, 'Stop', _px(_n(lv['sl'])), p.loss),
            _kv(p, 'Target', _px(_n(lv['tp'])), p.profit),
            _kv(p, 'Risk to stop', '${lv['risk_pct']}%'),
            Text('${lv['note']}', style: TextStyle(fontSize: 11, color: p.textMuted)),
          ],
        ]),
      ),
      OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(p, 'What the Brain saw'),
          for (final s in _s(r['saw'])) Padding(padding: const EdgeInsets.only(bottom: 4), child: Text(s, style: TextStyle(fontSize: 12.5, color: s.startsWith('Dhyan') ? p.warning : p.textPrimary))),
        ]),
      ),
      OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(p, 'Why not earlier', 'The Brain\'s older saved answers for this coin'),
          if (older.isEmpty) Text('No older answer is saved for this coin yet.', style: TextStyle(fontSize: 12.5, color: p.textSecondary)),
          for (final o in older)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Text('${o['time']}: ${'${o['decision']}'.replaceAll('_', ' ')} (${o['state']}) - ${o['reason']}', style: TextStyle(fontSize: 12.5, color: p.textPrimary)),
            ),
        ]),
      ),
      OWLCard(
        edge: ev['label'] == 'EVIDENCE' ? p.accent : p.warning,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(p, 'Evidence from similar trades'),
          Wrap(children: [_chip('${ev['label']}', ev['label'] == 'EVIDENCE' ? p.accent : p.warning)]),
          const SizedBox(height: 4),
          Text('${ev['text']}', style: TextStyle(fontSize: 12.5, color: p.textPrimary)),
          Text('Closed paper trades in all states: ${ev['all_closed']}. Evidence is not a promise.', style: TextStyle(fontSize: 11, color: p.textMuted)),
        ]),
      ),
      OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(p, 'Data to Brain'),
          _kv(p, 'Candles in the run', '${dt['candles']} (need ${dt['need']})'),
          _kv(p, 'From', '${dt['from']}'),
          _kv(p, 'To', '${dt['to']}'),
          Text('${dt['note']}', style: TextStyle(fontSize: 11, color: p.textMuted)),
        ]),
      ),
      Text('${r['paper_note']}', style: TextStyle(fontSize: 11, color: p.textMuted)),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final r = _r;
    final List<Widget> kids;
    if (_busy && r == null) {
      kids = [const Padding(padding: EdgeInsets.all(40), child: Center(child: CircularProgressIndicator()))];
    } else if (r == null || r['state'] != null || r['error'] != null) {
      kids = [OWLCard(edge: p.warning, child: Text(r != null && r['error'] != null ? '${r['error']}' : _problem(r ?? <String, dynamic>{'state': 'error'}), style: TextStyle(fontSize: 13, color: p.textPrimary)))];
    } else if (r['ready'] != true) {
      kids = [OWLCard(edge: p.warning, child: Text(_s(r['lines']).isNotEmpty ? _s(r['lines']).first : 'No data for this coin.', style: TextStyle(fontSize: 13, color: p.textPrimary)))];
    } else {
      kids = _body(p, r);
    }
    return Scaffold(
      appBar: AppBar(title: Text('Signal - ${widget.symbol}')),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(AppSpacing.l),
          children: [for (final k in kids) Padding(padding: const EdgeInsets.only(bottom: AppSpacing.m), child: k)],
        ),
      ),
    );
  }
}
