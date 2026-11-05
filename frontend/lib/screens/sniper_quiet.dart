import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';

/// Part 5 (FILE 08): the "Why is Sniper quiet?" card, shown at the TOP of the Sniper tab. Read only: it shows two gates side by side and never switches anything.
///  - LEARN gate (paper only, tiny size, tag LEARN): progress "LEARN trades n of 30", wins / losses / net, and the plain reasons the last background check opened nothing.
///  - REAL gate (85% floor, proven on the TEST days, armed): its state in one word. It is never lowered and never faked.
/// Data: [r] = the main Sniper answer (GET /api/v2/sniper), [learn] = GET /api/v2/sniper_learn (null while it loads). Every number comes from the backend. Dart NOT compiled (the APK build is the proof).

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
double _d(Object? v) => v is num ? v.toDouble() : 0.0;
String _usdt(Object? v) => '${_d(v) >= 0 ? '+' : ''}${_d(v).toStringAsFixed(2)} USDT';

const Map<String, String> _gateText = {
  'LEARN:signal': 'there was no Sniper signal on the card',
  'LEARN:fresh': 'the signal candle was too old',
  'LEARN:floor': 'the win chance was below the LEARN floor',
  'LEARN:stop': 'the stop distance was outside the allowed range',
  'LEARN:cap': 'the LEARN limit of open trades is full',
  'LEARN:kill': 'the LEARN loss limit or kill switch is on',
  'LEARN:duplicate': 'this exact signal was already traded',
  'LEARN:opener': 'the paper trader refused (the coin is already open in another bot, or no target price)',
  'LEARN:corr': 'too many trades in the same direction already move together (risk cluster limit)',
  'LEARN:mistake': 'this coin + side + market state lost its last 3 trades, so it rests 24 hours',
  'LEARN:switch': 'LEARN mode is switched off',
  'LEARN:state': 'the LEARN state file is broken',
  'LEARN:error': 'the LEARN gate failed',
  'REAL:kill': "the owner's kill switch is on (it stops both gates)",
  'REAL:corr': 'too many trades in the same direction already move together (risk cluster limit)',
  'REAL:state': 'the executor state file is broken (it stops both gates)',
};

class _Tag {
  final String word;
  final Color color;
  final String text;
  const _Tag(this.word, this.color, this.text);
}

class SniperQuiet extends StatelessWidget {
  final Map<String, dynamic> r;
  final Map<String, dynamic>? learn;
  const SniperQuiet({super.key, required this.r, required this.learn});

  Widget _chip(String text, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(color: c.withOpacity(0.15), borderRadius: BorderRadius.circular(20)),
        child: Text(text, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: c)),
      );

  _Tag _real(AppPalette p) {
    final ex = _m(r['executor']);
    if (ex.isEmpty || ex['state'] != null || ex['ok'] == false) return _Tag('NOT AVAILABLE', p.textMuted, 'The real executor is not in this backend.');
    if (_m(ex['kill'])['on'] == true) return _Tag('STOPPED', p.loss, 'The kill switch is on. Both gates are stopped.');
    if (r['floor_verified'] != true) {
      return _Tag('NOT PROVEN', p.warning, 'The 85% floor is not proven on the TEST days, so no REAL paper trade can open. The floor is never lowered.');
    }
    if (ex['armed'] != true) return _Tag('OFF', p.textSecondary, 'The floor is proven, but the executor is not armed. Arming is a 2-step Termux command.');
    return _Tag('ARMED', p.profit, 'Armed in paper mode. It opens a trade only when every check passes.');
  }

  List<String> _why(Map<String, dynamic> lt) {
    if (lt.isEmpty) return ['The background check has not run yet. It runs every 20 seconds.'];
    if (lt['auto'] == 'off') return ['The Sniper is switched off (the file v2_sniper_off exists).'];
    if (lt['auto'] == 'error') return ['The last check failed: ${lt['text'] ?? 'unknown error'}.'];
    final cards = _d(lt['cards']).toInt();
    if (cards == 0) {
      final n = _m(r['counts']);
      final g = _m(r['regimes']);
      return ['No coin has a Sniper signal right now. The Sniper\'s own checks stopped every coin (${_d(n['BLOCK_TRADE']).toInt()} blocked, ${_d(g['TRENDING']).toInt()} trending).'];
    }
    final e = _m(lt['why']).entries.toList()..sort((a, b) => _d(b.value).compareTo(_d(a.value)));
    return [for (final x in e.take(4)) '${_d(x.value).toInt()} of $cards signals: ${_gateText[x.key] ?? x.key}.'];
  }

  Widget _line(AppPalette p, String t, {Color? c, double size = 12}) =>
      Padding(padding: const EdgeInsets.only(top: 3), child: Text(t, style: TextStyle(fontSize: size, color: c ?? p.textSecondary)));

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final real = _real(p);
    final l = learn;
    String? problem;
    if (l == null) {
      problem = 'Loading the LEARN status...';
    } else if (l['state'] == 'off') {
      problem = 'The V2 data API is off, so the LEARN status cannot be read.';
    } else if (l['state'] == 'old') {
      problem = 'This backend has no LEARN route yet. Install the newest backend zip and restart the backend.';
    } else if (l['state'] != null) {
      problem = 'Cannot reach the backend for the LEARN status. Pull down to try again.';
    } else if (_m(l['learn'])['state'] == 'broken') {
      problem = '${_m(l['learn'])['text'] ?? 'The LEARN state file is broken.'}';
    }
    final realRow = Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _chip('REAL gate: ${real.word}', real.color),
      const SizedBox(width: 8),
      Expanded(child: Text(real.text, style: TextStyle(fontSize: 11.5, color: p.textMuted))),
    ]);
    if (problem != null) {
      return OWLCard(
        edge: l == null ? null : p.warning,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Why is Sniper quiet?', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
          _line(p, problem, c: p.textPrimary),
          const SizedBox(height: 10),
          realRow,
        ]),
      );
    }
    final ln = _m(l!['learn']);
    final pr = _m(ln['progress']);
    final n = _d(pr['n']).toInt();
    final target = _d(pr['target']) > 0 ? _d(pr['target']).toInt() : 30;
    final kill = _m(ln['kill'])['on'] == true;
    final isOn = ln['enabled'] != false;
    final lt = _m(l['last_turn']);
    final opened = lt['opened'] is List ? (lt['opened'] as List).length : 0;
    final c = kill ? p.loss : (isOn ? p.profit : p.textMuted);
    final open = ln['open'] is List ? (ln['open'] as List).length : 0;
    return OWLCard(
      edge: c,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('LEARN mode (paper only)', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary))),
          _chip(kill ? 'STOPPED' : (isOn ? 'ON' : 'OFF'), c),
        ]),
        const SizedBox(height: 8),
        Text('LEARN trades $n of $target', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary)),
        const SizedBox(height: 6),
        ClipRRect(
          borderRadius: BorderRadius.circular(6),
          child: LinearProgressIndicator(value: (n / target).clamp(0.0, 1.0), minHeight: 8, backgroundColor: p.border, color: p.accent),
        ),
        _line(p, '${pr['text'] ?? ''}', size: 11.5),
        _line(p, 'Won ${_d(pr['wins']).toInt()}  |  lost ${_d(pr['losses']).toInt()}  |  net ${_usdt(pr['net_usdt'])}  |  open now $open of ${_d(ln['max_open']).toInt()}', c: p.textPrimary),
        _line(p, 'Today ${_usdt(ln['day_pnl'])} (LEARN stops at -${_d(ln['daily_loss_limit']).toStringAsFixed(2)})  |  floor ${(_d(ln['floor']) * 100).toStringAsFixed(0)}%  |  ${_d(ln['size_usdt']).toStringAsFixed(1)} USDT per trade, 1x', size: 11.5, c: p.textMuted),
        if (kill) _line(p, 'LEARN stopped: ${_m(ln['kill'])['reason'] ?? ''}. Reset in Termux: python3 backend/owl_sniper_learn.py --data DIR reset_kill', c: p.loss, size: 11.5),
        const SizedBox(height: 12),
        Text(opened > 0 ? 'Last check: opened $opened paper trade(s).' : 'Last check: no trade opened. Why:', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: p.textPrimary)),
        if (opened == 0)
          for (final t in _why(lt))
            Padding(
              padding: const EdgeInsets.only(top: 3),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('\u2022  ', style: TextStyle(fontSize: 12, color: p.textMuted)),
                Expanded(child: Text(t, style: TextStyle(fontSize: 12, color: p.textPrimary))),
              ]),
            ),
        const SizedBox(height: 12),
        realRow,
      ]),
    );
  }
}
