import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// Short "RESULT" cards that sit at the top of the AI tabs.
/// One answer first, details below. Plain English. All numbers come from the
/// backend the old cards already use. Nothing here changes any trade.

double _n(dynamic v) => v is num ? v.toDouble() : 0.0;
int _i(dynamic v) => v is num ? v.toInt() : 0;
Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<dynamic> _l(dynamic v) => v is List ? v : const [];
String _sg(double v, {int d = 2}) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(d)}';

/// Loads one endpoint while its tab is open (old numbers show at once).
class _Loader extends StatefulWidget {
  final String peekPath;
  final Future<Map<String, dynamic>?> Function(AppProvider p) fetch;
  final TabController? tabs;
  final int tabIndex;
  final Widget Function(BuildContext context, Map<String, dynamic>? data, bool failed) builder;
  const _Loader({
    required this.peekPath,
    required this.fetch,
    required this.tabs,
    required this.tabIndex,
    required this.builder,
  });

  @override
  State<_Loader> createState() => _LoaderState();
}

class _LoaderState extends State<_Loader> {
  Map<String, dynamic>? _o;
  bool _failed = false;
  bool _busy = false;
  Timer? _timer;

  bool get _visible => widget.tabs == null || widget.tabs!.index == widget.tabIndex;

  void _onTab() {
    if (mounted && _visible && _o == null) _load();
  }

  @override
  void initState() {
    super.initState();
    _o = context.read<AppProvider>().peekAi(widget.peekPath);
    widget.tabs?.addListener(_onTab);
    Future.delayed(const Duration(milliseconds: 500), () {
      if (mounted && _visible) _load();
    });
    _timer = Timer.periodic(const Duration(seconds: 60), (_) {
      if (_visible) _load();
    });
  }

  @override
  void dispose() {
    widget.tabs?.removeListener(_onTab);
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    if (_busy || !mounted) return;
    _busy = true;
    final r = await widget.fetch(context.read<AppProvider>());
    _busy = false;
    if (!mounted) return;
    setState(() {
      if (r != null) {
        _o = r;
        _failed = false;
      } else if (_o == null) {
        _failed = true;
      }
    });
  }

  @override
  Widget build(BuildContext context) => widget.builder(context, _o, _failed);
}

Widget _shell(
  BuildContext context, {
  required String owner,
  required String headline,
  Color? color,
  List<String> lines = const [],
  Widget? extra,
}) {
  final p = context.palette;
  return Container(
    width: double.infinity,
    margin: const EdgeInsets.only(bottom: 10),
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(
      color: p.surfaceElevated,
      borderRadius: BorderRadius.circular(AppSpacing.radiusMedium + 2),
      border: Border.all(color: (color ?? p.accent).withOpacity(0.55), width: 1),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(owner, style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w800, letterSpacing: 1.2, color: p.textMuted)),
        const SizedBox(height: 6),
        Text(headline, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, height: 1.3, color: color ?? p.textPrimary)),
        for (final l in lines)
          Padding(
            padding: const EdgeInsets.only(top: 5),
            child: Text(l, style: TextStyle(fontSize: 12.5, height: 1.4, color: p.textSecondary)),
          ),
        if (extra != null) extra,
      ],
    ),
  );
}

Widget _loading(BuildContext context, String owner, bool failed) => _shell(
      context,
      owner: owner,
      headline: failed ? 'Could not load this result. Pull down to try again.' : 'Loading the result...',
    );

// ------------------------------------------------------------------ TRAIL

/// Trail Filter tab: does a different trailing stop beat the bot's own?
class AiTrailSummary extends StatelessWidget {
  final TabController? tabs;
  final int tabIndex;
  const AiTrailSummary({super.key, this.tabs, this.tabIndex = 0});

  @override
  Widget build(BuildContext context) {
    return _Loader(
      peekPath: '/api/ai/observer',
      fetch: (p) => p.fetchAiObserver(),
      tabs: tabs,
      tabIndex: tabIndex,
      builder: (context, o, failed) {
        const owner = 'TRAIL FILTER  ·  RESULT';
        final p = context.palette;
        if (o == null) return _loading(context, owner, failed);
        Map<String, dynamic> pol(String key) {
          for (final x in _l(o['policies'])) {
            final m = _m(x);
            if (m['key'] == key) return m;
          }
          return <String, dynamic>{};
        }

        final n = _i(o['n']);
        if ((o['status'] ?? '') != 'OK' || n < 30) {
          return _shell(context,
              owner: owner,
              headline: 'Not enough trades yet',
              lines: [
                '$n bot trades have a saved journey. A result needs 30 or more.',
                'This tab replays the same bot trades with two other trailing stop rules and compares them with the bot.',
              ]);
        }
        final bot = pol('BOT');
        final s1 = pol('STEP1');
        final s2 = pol('STEP2');
        final hasUsdt = bot['usdt'] != null && s1['usdt'] != null && s2['usdt'] != null;
        double tot(Map<String, dynamic> m) => hasUsdt ? _n(m['usdt']) : _n(m['total']);
        final unit = hasUsdt ? 'USDT' : '%';
        final d1 = tot(s1) - tot(bot);
        final d2 = tot(s2) - tot(bot);
        final bestName = d1 >= d2 ? 'STEP1' : 'STEP2';
        final best = d1 >= d2 ? s1 : s2;
        final bestDiff = d1 >= d2 ? d1 : d2;
        String word(String v) {
          switch (v) {
            case 'CLEAR':
              return 'clearly better (older and newer trades agree)';
            case 'MAYBE':
              return 'maybe better, not proven yet';
            case 'SAME':
              return 'about the same as the bot';
            case 'WORSE':
              return 'worse than the bot';
            default:
              return 'still collecting data';
          }
        }

        final ee = _m(o['entry_exit']);
        final never = _m(ee['never']);
        final gave = _m(ee['gave_back']);
        final kept = _m(ee['kept']);
        return _shell(
          context,
          owner: owner,
          color: bestDiff > 0 ? p.profit : p.textSecondary,
          headline: bestDiff > 0
              ? '$bestName would have made ${_sg(bestDiff, d: 1)} $unit more than the bot'
              : 'The bot\'s own trailing is still the best',
          lines: [
            '$bestName verdict: ${word((best['verdict'] ?? '').toString())}.',
            'Where the bot trades end: ${_i(never['n'])} never reached TP1, ${_i(gave['n'])} reached TP1 and then lost, ${_i(kept['n'])} kept their profit. Trailing can only help the middle group.',
            'Based on $n past bot trades, fee included. Replay only: the live bot is not changed.',
          ],
        );
      },
    );
  }
}

// ------------------------------------------------------------- BOT VS AI

/// Bot vs AI tab: did the AI's own choices beat the bot, and why did it skip?
class AiVersusSummary extends StatelessWidget {
  final TabController? tabs;
  final int tabIndex;
  const AiVersusSummary({super.key, this.tabs, this.tabIndex = 0});

  @override
  Widget build(BuildContext context) {
    return _Loader(
      peekPath: '/api/ai/desk',
      fetch: (p) => p.fetchAiDesk(),
      tabs: tabs,
      tabIndex: tabIndex,
      builder: (context, o, failed) {
        const owner = 'BOT VS AI  ·  RESULT';
        final p = context.palette;
        if (o == null) return _loading(context, owner, failed);
        final calls = _m(o['calls']);
        final total = _i(o['signals']);
        final le = _i(calls['LE']);
        final sk = _i(calls['SKIP']);
        final wt = _i(calls['WAIT']);
        final cmp = _m(o['compare']);
        final cn = _i(cmp['n']);
        final diff = _n(cmp['diff']);
        final skipped = _m(o['skipped']);
        final sClosed = _i(skipped['closed']);
        final sPnl = _n(skipped['bot_pnl']);

        String headline;
        Color? color;
        if (cn < 5) {
          headline = 'The AI is still learning. It needs 5 closed signals before the comparison is fair.';
        } else if (diff > 0) {
          headline = 'The AI is ahead of the bot by ${_sg(diff)} USDT on $cn closed signals';
          color = p.profit;
        } else if (diff < 0) {
          headline = 'The AI is behind the bot by ${diff.abs().toStringAsFixed(2)} USDT on $cn closed signals';
          color = p.loss;
        } else {
          headline = 'The AI and the bot are equal on $cn closed signals';
        }

        final lines = <String>[
          'Out of $total bot signals the AI took $le, skipped $sk and waited on $wt.',
        ];
        if (sClosed > 0) {
          lines.add('On the $sClosed signals the AI left out, the bot made ${_sg(sPnl)} USDT '
              '(${_i(skipped['bot_wins'])} won, ${_i(skipped['bot_losses'])} lost). '
              '${sPnl < 0 ? 'So leaving them out helped.' : (sPnl > 0 ? 'So leaving them out cost some profit.' : 'So it made no difference.')}');
        }

        // Why the AI stayed out: the most common reasons in its last decisions.
        final reasons = <String, int>{};
        for (final r in _l(o['recent'])) {
          final m = _m(r);
          if ((m['call'] ?? '') == 'LE') continue;
          final w = (m['why'] ?? '').toString().trim();
          if (w.isEmpty) continue;
          final key = w.length > 70 ? '${w.substring(0, 70)}...' : w;
          reasons[key] = (reasons[key] ?? 0) + 1;
        }
        final top = reasons.entries.toList()..sort((a, b) => b.value.compareTo(a.value));
        if (top.isNotEmpty) {
          lines.add('Why it stayed out (last 15 decisions):');
          for (final e in top.take(3)) {
            lines.add('•  ${e.key}  (${e.value}x)');
          }
        }
        lines.add('What the AI found about each indicator is in the Learned tab.');
        return _shell(context, owner: owner, headline: headline, color: color, lines: lines);
      },
    );
  }
}

// --------------------------------------------------------------- FREE AI

/// Free AI tab: how the AI's own, unrestricted trades are doing.
class AiFreeSummary extends StatelessWidget {
  final TabController? tabs;
  final int tabIndex;
  const AiFreeSummary({super.key, this.tabs, this.tabIndex = 0});

  @override
  Widget build(BuildContext context) {
    return _Loader(
      peekPath: '/api/ai/selfsignal',
      fetch: (p) => p.fetchAiSelfSignal(),
      tabs: tabs,
      tabIndex: tabIndex,
      builder: (context, o, failed) {
        const owner = 'FREE AI  ·  RESULT';
        final p = context.palette;
        if (o == null) return _loading(context, owner, failed);
        if (o['error'] != null) {
          return _shell(context, owner: owner, headline: 'The Free AI could not report right now.', lines: ['${o['error']}']);
        }
        if (o['enabled'] == false) {
          return _shell(context, owner: owner, headline: 'The Free AI is switched off.');
        }
        final mine = _m(o['mine']);
        final bot = _m(o['bot']);
        final money = _m(o['money']);
        final margin = money['margin'] is num ? _n(money['margin']) : null;
        final n = _i(mine['n']);
        final lines = <String>[];
        String headline;
        Color? color;
        Widget? moneyRow;
        if (margin != null) {
          Widget cell(String label, String value, Color c) => Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(label, style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: p.textMuted)),
                    const SizedBox(height: 2),
                    Text(value, style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w800, color: c)),
                  ],
                ),
              );
          Color sc(double v) => v > 0 ? p.profit : (v < 0 ? p.loss : p.textPrimary);
          final closedU = _n(money['closed_usdt']);
          final openU = _n(money['open_usdt']);
          moneyRow = Padding(
            padding: const EdgeInsets.only(top: 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    cell('MARGIN IN USE', '${_n(money['margin_in_use']).toStringAsFixed(0)} USDT', p.textPrimary),
                    cell('CLOSED P&L', '${_sg(closedU)} USDT', sc(closedU)),
                    cell('OPEN P&L', '${_sg(openU)} USDT', sc(openU)),
                  ],
                ),
                const SizedBox(height: 8),
                Text(
                  'Each trade uses ${margin.toStringAsFixed(margin == margin.roundToDouble() ? 0 : 2)} USDT margin at ${_n(money['lev']).toStringAsFixed(0)}x (Settings > Invest Amount, the same as the bot). '
                  '${_i(money['closed_n'])} closed trades used ${_n(money['margin_closed']).toStringAsFixed(0)} USDT of margin in total: '
                  '${_i(money['win_n'])} won ${_sg(_n(money['won_usdt']))} USDT, ${_i(money['loss_n'])} lost ${_sg(_n(money['lost_usdt']))} USDT. '
                  'Open P&L is live and after fee.',
                  style: TextStyle(fontSize: 11.5, height: 1.4, color: p.textMuted),
                ),
              ],
            ),
          );
        } else if (money.isNotEmpty) {
          lines.add('Settings use a percent of balance for the trade size, so the result cannot be shown in USDT here.');
        }
        if (n == 0) {
          headline = 'The Free AI has not closed a trade yet';
          final why = (o['gate_why'] ?? '').toString();
          if (why.isNotEmpty && o['gate_open'] != true) lines.add(why);
        } else {
          final avg = _n(mine['avg']);
          if (margin != null) {
            final tot = _n(money['total_usdt']);
            headline = 'Free AI total: ${_sg(tot)} USDT  ·  $n closed, ${_n(mine['wr']).toStringAsFixed(0)}% won';
            color = tot > 0 ? p.profit : (tot < 0 ? p.loss : null);
            lines.add('Average per closed trade: ${_sg(avg)}% of margin.');
          } else {
            headline = '$n trades closed, ${_n(mine['wr']).toStringAsFixed(0)}% won, average ${_sg(avg)}% per trade';
            color = avg > 0 ? p.profit : (avg < 0 ? p.loss : null);
          }
          final bn = _i(bot['n']);
          if (bn > 0) {
            lines.add('For comparison the bot: $bn trades, ${_n(bot['wr']).toStringAsFixed(0)}% won, average ${_sg(_n(bot['avg']))}% per trade.');
          }
        }
        lines.add('Open now: ${_i(o['open'])} trade(s). Paper money only. It enters, moves its stop and exits by its own reading of the indicators.');
        final learned = _m(o['learned']);
        String pretty(dynamic s) => '$s'.replaceAll('|', ' · ');
        for (final b in _l(learned['best']).take(2)) {
          final m = _m(b);
          lines.add('Works best so far: ${pretty(m['read'])}  (average ${_sg(_n(m['avg']))}%, ${_i(m['n'])} trades)');
        }
        for (final w in _l(learned['worst']).take(2)) {
          final m = _m(w);
          lines.add('Works worst so far: ${pretty(m['read'])}  (average ${_sg(_n(m['avg']))}%, ${_i(m['n'])} trades)');
        }
        final v = (o['verdict'] ?? '').toString();
        if (v.isNotEmpty) lines.add(v);
        return _shell(context, owner: owner, headline: headline, color: color, lines: lines, extra: moneyRow);
      },
    );
  }
}

// --------------------------------------------------------------- LEARNED

/// Learned tab: what the AI found, only by counting real candles.
class AiLearnedCard extends StatelessWidget {
  final TabController? tabs;
  final int tabIndex;
  const AiLearnedCard({super.key, this.tabs, this.tabIndex = 0});

  @override
  Widget build(BuildContext context) {
    return _Loader(
      peekPath: '/api/ai/levels',
      fetch: (p) => p.fetchAiLevels(),
      tabs: tabs,
      tabIndex: tabIndex,
      builder: (context, o, failed) {
        const owner = 'WHAT THE AI HAS LEARNED  ·  INDICATORS';
        final p = context.palette;
        if (o == null) return _loading(context, owner, failed);
        final n = _i(o['n']);
        final need = _i(o['need']);
        if ((o['status'] ?? '') != 'OK') {
          return _shell(context,
              owner: owner,
              headline: 'Still collecting: $n of $need chart events',
              lines: [
                'The AI watches the coins and counts what price does after it touches an SD line or Z-SMA crosses.',
                'Nothing is told to it. A result appears when there are enough events.',
              ]);
        }
        final sits = _l(o['situations']).map(_m).toList();
        final good = sits.where((s) => s['verdict'] == 'GOOD').toList();
        final bad = sits.where((s) => s['verdict'] == 'BAD').toList();

        Color vColor(String v) => v == 'GOOD' ? p.profit : (v == 'BAD' ? p.loss : p.textMuted);
        String vWord(String v, bool z) {
          switch (v) {
            case 'GOOD':
              return z ? 'Follows' : 'Bounces';
            case 'BAD':
              return z ? 'Fails' : 'Breaks';
            case 'COLLECTING':
              return 'Collecting';
            default:
              return 'No edge';
          }
        }

        Widget row(Map<String, dynamic> s, {bool showOldNew = false}) {
          final label = '${s['label']}';
          final z = label.startsWith('ZSMA');
          final rate = _n(s['rate']);
          final v = '${s['verdict']}';
          final a = z ? 'followed' : 'bounced back';
          final b = z ? 'failed' : 'broke through';
          return Padding(
            padding: const EdgeInsets.only(top: 7),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(label, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: p.textPrimary)),
                      Text(
                        '${rate.toStringAsFixed(0)}% $a  ·  ${(100 - rate).toStringAsFixed(0)}% $b  ·  ${_i(s['n'])} events'
                        '${showOldNew && s['old'] != null ? '  ·  older ${_n(s['old']).toStringAsFixed(0)}% / newer ${_n(s['new']).toStringAsFixed(0)}%' : ''}',
                        style: TextStyle(fontSize: 11.5, height: 1.3, color: p.textMuted),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                Text(vWord(v, z), style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800, color: vColor(v))),
              ],
            ),
          );
        }

        final extra = Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SizedBox(height: 10),
            Text('BY LEVEL', style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w800, letterSpacing: 1.2, color: p.textMuted)),
            for (final lv in _l(o['levels']).map(_m)) row(lv),
            const SizedBox(height: 14),
            Text('BY SITUATION (level + volatility + TSI + Z-SMA)',
                style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w800, letterSpacing: 1.2, color: p.textMuted)),
            if (good.isEmpty && bad.isEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 7),
                child: Text('No situation is proven yet. It must hold in both the older and the newer events.',
                    style: TextStyle(fontSize: 12, height: 1.4, color: p.textSecondary)),
              ),
            for (final s in [...good.take(4), ...bad.take(4)]) row(s, showOldNew: true),
            const SizedBox(height: 12),
            Text(
              'The AI only counts what happened on real candles. No rule was written for it. 50% is a coin flip. '
              'A level is called "Bounces" or "Breaks" only when it holds in the older and the newer events.',
              style: TextStyle(fontSize: 11.5, height: 1.4, color: p.textMuted),
            ),
          ],
        );
        return _shell(
          context,
          owner: owner,
          headline: (good.isEmpty && bad.isEmpty)
              ? 'From $n events, no indicator situation is proven yet'
              : 'From $n events: ${good.length} situation(s) proven to bounce or follow, ${bad.length} proven to break or fail',
          color: (good.isEmpty && bad.isEmpty) ? null : p.accent,
          extra: extra,
        );
      },
    );
  }
}
