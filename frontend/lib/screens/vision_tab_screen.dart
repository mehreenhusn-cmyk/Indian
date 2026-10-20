import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../theme/app_motion.dart';
import '../theme/app_spacing.dart';
import '../utils/format.dart';
import '../widgets/ai_chat_popup.dart';
import '../widgets/owl_eye_dot.dart';
import '../widgets/owl_pressable.dart';
import '../widgets/owl_refresh.dart';
import '../widgets/vision_notebook_view.dart';
import '../widgets/vision_pumpdump_view.dart';

/// The AI tab (Vision AI).
///   Live     - the AI's own virtual account: open trades with live P&L, stop and target, and what the AI says about them.
///   Signals  - every bot signal and what the AI decided (take / skip / wait) with the reason.
///   Results  - how the AI trades did, and what the bot did on the signals the AI took or skipped.
///   Guide    - what the AI is told about your indicators, plus your own notes.
///   Notebook - what the AI learned from its own closed trades: lessons, and rules you approve or delete.
/// Tap any row to see the exact chart the AI looked at, its checklist and its notes.
/// All numbers come from the backend (ai_vision.py). The phone only draws them.

Map<String, dynamic> _m(dynamic x) => x is Map ? Map<String, dynamic>.from(x) : <String, dynamic>{};
List _l(dynamic x) => x is List ? x : const [];
double? _d(dynamic x) {
  if (x is num) return x.toDouble();
  if (x is String) return double.tryParse(x);
  return null;
}

String _px(dynamic v) {
  final d = _d(v);
  if (d == null || d == 0) return '-';
  final a = d.abs();
  final dec = a >= 100 ? 2 : (a >= 1 ? 4 : (a >= 0.01 ? 5 : 7));
  return d.toStringAsFixed(dec);
}

String _hm(dynamic t) {
  final v = _d(t);
  if (v == null || v <= 0) return '';
  final dt = DateTime.fromMillisecondsSinceEpoch((v * 1000).round());
  final h = dt.hour.toString().padLeft(2, '0');
  final m = dt.minute.toString().padLeft(2, '0');
  return '$h:$m';
}

String _statusLabel(String s) {
  switch (s) {
    case 'taken':
      return 'TAKEN';
    case 'waiting':
      return 'WAITING';
    case 'queued':
      return 'IN LINE';
    case 'late':
      return 'TOO LATE';
    case 'error':
      return 'ERROR';
    default:
      return 'SKIPPED';
  }
}

Color _statusColor(AppPalette p, String s) {
  switch (s) {
    case 'taken':
      return p.profit;
    case 'waiting':
      return p.warning;
    case 'error':
      return p.loss;
    case 'queued':
    case 'late':
      return p.textMuted;
    default:
      return p.textSecondary;
  }
}

const Map<String, String> _checkNames = {
  'ema': 'EMA',
  'candles': 'Candles',
  'sd_zone': 'SD zone',
  'tsi': 'TSI',
  'zscore': 'Z-score',
  'divergence': 'Divergence',
  'room': 'Room to move',
  'momentum': 'Momentum',
  'bands': 'Bands',
};

class VisionTabScreen extends StatefulWidget {
  const VisionTabScreen({super.key});

  @override
  State<VisionTabScreen> createState() => _VisionTabScreenState();
}

class _VisionTabScreenState extends State<VisionTabScreen> {
  static int _lastTab = 0;
  int _tab = _lastTab;
  String _filter = 'All';
  Map<String, dynamic>? _data;
  Map<String, dynamic>? _guide;
  bool _failed = false;
  Timer? _timer;
  final TextEditingController _notes = TextEditingController();
  bool _notesLoaded = false;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 12), (_) {
      if (mounted && TickerMode.of(context)) _load();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _notes.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final r = await context.read<AppProvider>().fetchVisionState();
    if (!mounted) return;
    setState(() {
      if (r != null) {
        _data = r;
        _failed = false;
      } else if (_data == null) {
        _failed = true;
      }
    });
  }

  Future<void> _loadGuide() async {
    if (_guide != null) return;
    final g = await context.read<AppProvider>().fetchVisionGuide();
    if (!mounted || g == null) return;
    setState(() {
      _guide = g;
      if (!_notesLoaded) {
        _notes.text = (g['notes'] ?? '').toString();
        _notesLoaded = true;
      }
    });
  }

  Future<void> _saveNotes() async {
    setState(() => _saving = true);
    final ok = await context.read<AppProvider>().saveVisionNotes(_notes.text);
    if (!mounted) return;
    setState(() => _saving = false);
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(ok ? 'Notes saved. The AI reads them from the next chart.' : 'Could not save. Check the connection.')));
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _data;
    final provider = (d?['provider'] ?? '').toString();
    final model = (d?['model'] ?? '').toString();
    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        heroTag: 'ai_ask_fab',
        backgroundColor: p.purple,
        foregroundColor: Colors.white,
        elevation: 3,
        icon: const Icon(Icons.auto_awesome_rounded, size: 18),
        label: const Text('Ask AI', style: TextStyle(fontWeight: FontWeight.w700)),
        onPressed: () {
          AppHaptics.light();
          showAiChatPopup(context);
        },
      ),
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.m, AppSpacing.l, AppSpacing.s),
              child: Row(
                children: [
                  OwlEyeDot(live: d != null && d['ready'] == true, color: p.owlEye, size: 8),
                  const SizedBox(width: 8),
                  Text('AI', style: context.type.hero.copyWith(fontSize: 24)),
                  const Spacer(),
                  Flexible(
                    child: Text(
                      model.isNotEmpty ? 'Vision AI  ·  $model' : (provider.isNotEmpty ? 'Vision AI  ·  $provider' : 'Vision AI'),
                      overflow: TextOverflow.ellipsis,
                      style: context.type.metadata,
                    ),
                  ),
                ],
              ),
            ),
            _tabStrip(p),
            const SizedBox(height: AppSpacing.s),
            Expanded(child: _body(p)),
          ],
        ),
      ),
    );
  }

  Widget _tabStrip(AppPalette p) {
    const labels = ['Live', 'Signals', 'Results', 'Guide', 'Notebook', 'Pump'];
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: AppSpacing.l),
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        color: p.surfaceHigher,
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
        border: Border.all(color: p.border, width: 0.6),
      ),
      child: Row(
        children: [
          for (var i = 0; i < labels.length; i++)
            Expanded(
              child: OWLPressable(
                pressedScale: 0.97,
                onTap: () {
                  AppHaptics.light();
                  setState(() {
                    _tab = i;
                    _lastTab = i;
                  });
                  if (i == 3) _loadGuide();
                },
                child: AnimatedContainer(
                  duration: AppMotion.base,
                  padding: const EdgeInsets.symmetric(vertical: 9),
                  decoration: BoxDecoration(
                    color: _tab == i ? p.accent.withOpacity(0.16) : Colors.transparent,
                    borderRadius: BorderRadius.circular(AppSpacing.radiusSmall + 1),
                  ),
                  alignment: Alignment.center,
                  child: Text(
                    labels[i],
                    style: TextStyle(
                      fontSize: 12.5,
                      fontWeight: _tab == i ? FontWeight.w800 : FontWeight.w500,
                      color: _tab == i ? p.accent : p.textMuted,
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _body(AppPalette p) {
    if (_tab == 5) {
      return const VisionPumpdumpView();
    }
    if (_tab == 4) {
      return const VisionNotebookView();
    }
    if (_tab == 3) {
      _loadGuide();
      return _guideTab(p);
    }
    final d = _data;
    if (d == null) {
      return Center(
        child: _failed
            ? Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text('Could not reach the backend.', style: context.type.metadata),
                  const SizedBox(height: 8),
                  TextButton(onPressed: _load, child: const Text('Retry')),
                ],
              )
            : const CircularProgressIndicator(strokeWidth: 2),
      );
    }
    switch (_tab) {
      case 1:
        return _signalsTab(p, d);
      case 2:
        return _resultsTab(p, d);
      default:
        return _liveTab(p, d);
    }
  }

  // ------------------------------------------------------------------ shared pieces
  Widget _banner(AppPalette p, Map<String, dynamic> d) {
    final msg = (d['message'] ?? '').toString();
    if (msg.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.cardGap),
      child: _VCard(
        glow: p.warning,
        child: Row(
          children: [
            Icon(Icons.info_outline_rounded, size: 18, color: p.warning),
            const SizedBox(width: 10),
            Expanded(child: Text(msg, style: context.type.metadata.copyWith(color: p.textPrimary, height: 1.35))),
          ],
        ),
      ),
    );
  }

  String _hhmm(double? t) {
    if (t == null || t <= 0) return '';
    final dt = DateTime.fromMillisecondsSinceEpoch((t * 1000).toInt());
    return '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
  }

  /// "AI Calls" card: how many calls the keys made in the last 24 h, which key answers, and why signals wait. Numbers come from the backend.
  Widget _monitorCard(AppPalette p, Map<String, dynamic> d) {
    final m = _m(d['monitor']);
    if (m.isEmpty) return const SizedBox.shrink();
    final slots = _l(m['slots']).map(_m).toList();
    final used = (_d(m['used_24h']) ?? 0).toInt();
    final cap = (_d(m['cap']) ?? 0).toInt();
    final waiting = (_d(m['waiting']) ?? 0).toInt();
    final tip = (m['tip'] ?? '').toString();
    final err = (m['last_error'] ?? '').toString();
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.cardGap),
      child: _VCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const _VLabel('AI CALLS (LAST 24 HOURS)'),
            const SizedBox(height: 8),
            Text(cap > 0 ? '$used of $cap calls used (your daily cap in the app)' : '$used calls made',
                style: TextStyle(color: p.textPrimary, fontSize: 13, fontWeight: FontWeight.w700)),
            if (cap > 0) ...[
              const SizedBox(height: 6),
              ClipRRect(
                borderRadius: BorderRadius.circular(4),
                child: LinearProgressIndicator(value: (used / cap).clamp(0.0, 1.0), minHeight: 5, backgroundColor: p.border, color: p.accent),
              ),
            ],
            const SizedBox(height: 10),
            for (final sl in slots)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text('${sl['slot'] == 'main' ? 'Main key' : sl['slot'] == 'backup' ? 'Backup key 1' : sl['slot'] == 'backup2' ? 'Backup key 2' : 'Backup key 3'}  ·  ${_provName((sl['provider'] ?? '').toString())}',
                              style: TextStyle(color: p.textPrimary, fontSize: 12.5, fontWeight: FontWeight.w800)),
                        ),
                        Text(sl['state'] == 'paused' ? 'OUT OF QUOTA' : 'READY',
                            style: TextStyle(color: sl['state'] == 'paused' ? p.warning : p.profit, fontSize: 10.5, fontWeight: FontWeight.w800)),
                      ],
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '${sl['calls'] ?? 0} calls  ·  ${sl['ok'] ?? 0} worked  ·  ${sl['quota'] ?? 0} quota stops  ·  ${sl['errors'] ?? 0} errors'
                      '${sl['avg_s'] != null ? '  ·  avg ${sl['avg_s']} s' : ''}'
                      '${sl['state'] == 'paused' && _hhmm(_d(sl['paused_until'])).isNotEmpty ? '  ·  back about ${_hhmm(_d(sl['paused_until']))}' : ''}',
                      style: context.type.metadata.copyWith(fontSize: 11, height: 1.35),
                    ),
                    if ((sl['model'] ?? '').toString().isNotEmpty)
                      Text('Model: ${sl['model']}', style: context.type.metadata.copyWith(fontSize: 10.5, height: 1.3)),
                    if ((sl['last_error'] ?? '').toString().isNotEmpty)
                      Text(_plainErr((sl['last_error'] ?? '').toString()), style: context.type.metadata.copyWith(fontSize: 10.5, height: 1.3, color: p.warning)),
                  ],
                ),
              ),
            if (waiting > 0)
              Text('$waiting signal(s) are waiting for the AI.', style: context.type.metadata.copyWith(color: p.textPrimary, height: 1.35)),
            if (tip.isNotEmpty) Text(tip, style: context.type.metadata.copyWith(height: 1.35)),
            if (err.isNotEmpty && slots.every((x) => x['state'] == 'paused'))
              Padding(
                padding: const EdgeInsets.only(top: 3),
                child: Text('Last AI message: ${err.length > 140 ? err.substring(0, 140) : err}', style: context.type.metadata.copyWith(fontSize: 10.5, height: 1.35)),
              ),
          ],
        ),
      ),
    );
  }

  Widget _section(String text) => Padding(
        padding: const EdgeInsets.only(top: 6, bottom: 8),
        child: _VLabel(text),
      );

  Widget _empty(String text) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 18),
        child: Center(child: Text(text, textAlign: TextAlign.center, style: context.type.metadata.copyWith(height: 1.4))),
      );

  EdgeInsets get _pad => const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.s, AppSpacing.l, 96);

  // ------------------------------------------------------------------ plain-words helpers (Live + Results)
  static String _provName(String x) {
    switch (x) {
      case 'gemini':
        return 'Gemini';
      case 'anthropic':
        return 'Claude';
      case 'openai':
        return 'OpenAI';
      case 'groq':
        return 'Groq';
      case 'mistral':
        return 'Mistral';
      case 'openrouter':
        return 'OpenRouter';
    }
    return x;
  }

  /// Turns a raw API error into one short sentence the owner can act on.
  static String _plainErr(String e) {
    final s = e.toLowerCase();
    if (s.isEmpty) return '';
    if (s.contains('404') || s.contains('not found')) return 'Model name not found. Open Settings > AI keys and press "Detect again".';
    if (s.contains('401') || s.contains('403') || s.contains('key problem') || s.contains('incorrect api key')) return 'The key is not accepted. Create a new key and paste it again.';
    if (s.contains('429') || s.contains('quota') || s.contains('rate')) return 'Out of free calls for now. It comes back by itself.';
    if (s.contains('network') || s.contains('timed out')) return 'No internet for a moment.';
    return e.length > 110 ? e.substring(0, 110) : e;
  }

  /// Wins, losses and the numbers a trader checks: profit factor (money won / money lost), average win, average loss.
  Map<String, double> _stats(List closed) {
    double gp = 0, gl = 0;
    int w = 0, l = 0;
    for (final x in closed) {
      final v = _d(_m(x)['pnl']) ?? 0;
      if (v >= 0) {
        gp += v;
        w++;
      } else {
        gl += -v;
        l++;
      }
    }
    return {
      'gp': gp,
      'gl': gl,
      'w': w.toDouble(),
      'l': l.toDouble(),
      'pf': gl == 0 ? (gp > 0 ? 9.99 : 0.0) : gp / gl,
      'avgW': w == 0 ? 0.0 : gp / w,
      'avgL': l == 0 ? 0.0 : gl / l,
    };
  }

  /// A labelled bar. [mark] draws a thin line (for example the 50% win-rate line or the break-even line).
  Widget _meterBar(AppPalette p, String label, String value, double frac, Color c, String hint, {double? mark}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Expanded(child: Text(label, style: TextStyle(color: p.textPrimary, fontSize: 12, fontWeight: FontWeight.w800))),
            Text(value, style: TextStyle(color: c, fontSize: 12, fontWeight: FontWeight.w800)),
          ]),
          const SizedBox(height: 4),
          SizedBox(
            height: 7,
            child: LayoutBuilder(builder: (ctx, cs) {
              final w = cs.maxWidth;
              final f = frac.clamp(0.0, 1.0).toDouble();
              return Stack(children: [
                Container(decoration: BoxDecoration(color: p.border, borderRadius: BorderRadius.circular(4))),
                Container(width: w * f, decoration: BoxDecoration(color: c, borderRadius: BorderRadius.circular(4))),
                if (mark != null)
                  Positioned(left: w * mark.clamp(0.0, 1.0).toDouble() - 1, top: 0, bottom: 0, child: Container(width: 2, color: p.textPrimary.withOpacity(0.55))),
              ]);
            }),
          ),
          const SizedBox(height: 3),
          Text(hint, style: context.type.metadata.copyWith(fontSize: 10.5, height: 1.3)),
        ],
      ),
    );
  }

  /// One plain sentence: what happened in the AI account.
  String _liveStory(Map<String, dynamic> s, Map<String, dynamic> d) {
    final closedN = (_d(s['closed']) ?? 0).toInt();
    final wins = (_d(s['wins']) ?? 0).toInt();
    final net = _d(s['net']) ?? 0;
    final unreal = _d(s['unrealized']) ?? 0;
    final opens = _l(d['open']).length;
    if (closedN == 0) {
      return opens > 0
          ? 'No AI trade has finished yet. $opens open now, so the P&L above is only their live value.'
          : 'The AI has not taken a trade yet. It looks at every bot signal and only takes the ones it likes.';
    }
    final dir = net >= 0 ? 'up' : 'down';
    final openText = opens > 0 ? '$opens still open, worth ${fmtSigned(unreal)} right now.' : 'Nothing is open now.';
    return 'The AI account is $dir ${net.abs().toStringAsFixed(2)} USDT on $closedN finished trades (${wins} won, ${closedN - wins} lost). $openText';
  }

  List<Widget> _liveMeters(AppPalette p, Map<String, dynamic> s, Map<String, dynamic> d) {
    final closed = _l(d['closed']);
    final closedN = (_d(s['closed']) ?? 0).toInt();
    if (closedN == 0) return const <Widget>[];
    final win = _d(s['win_rate']) ?? 0;
    final st = _stats(closed);
    final pf = st['pf'] ?? 0;
    final avgW = st['avgW'] ?? 0;
    final avgL = st['avgL'] ?? 0;
    final winC = win >= 55 ? p.profit : (win >= 45 ? p.warning : p.loss);
    final pfC = pf >= 1.3 ? p.profit : (pf >= 1.0 ? p.warning : p.loss);
    return <Widget>[
      _meterBar(p, 'Win rate', '${win.toStringAsFixed(0)}%', win / 100.0, winC, 'Share of finished trades that made money. The thin line is 50%.', mark: 0.5),
      _meterBar(p, 'Profit factor', pf.toStringAsFixed(2), pf / 3.0, pfC,
          'Money won divided by money lost (last ${closed.length} trades). Above 1.0 = profitable. The thin line is 1.0.',
          mark: 1.0 / 3.0),
      Text(
        'Average win +${avgW.toStringAsFixed(2)}  ·  average loss -${avgL.toStringAsFixed(2)} USDT'
        '${avgL > 0 ? '  ·  win/loss size ${(avgW / avgL).toStringAsFixed(2)}x' : ''}',
        style: context.type.metadata.copyWith(fontSize: 11, height: 1.35),
      ),
    ];
  }

  /// Results: one verdict (TOO EARLY / WEAK / OKAY / GOOD) with the reasons in plain words and a short technical line.
  Widget _verdictCard(AppPalette p, Map<String, dynamic> d) {
    final s = _m(d['summary']);
    final taken = _m(s['bot_on_taken']);
    final skipped = _m(s['bot_on_skipped']);
    final st = _stats(_l(d['closed']));
    final n = (_d(s['closed']) ?? 0).toInt();
    final net = _d(s['net']) ?? 0;
    final skipNet = _d(skipped['net']) ?? 0;
    final skipN = (_d(skipped['n']) ?? 0).toInt();
    final takenNet = _d(taken['net']) ?? 0;
    final takenN = (_d(taken['n']) ?? 0).toInt();
    final pf = st['pf'] ?? 0;
    String title = 'TOO EARLY';
    Color c = p.textMuted;
    double frac = n / 20.0;
    String meterValue = '$n of 20 trades';
    String meterLabel = 'Data collected';
    String meterHint = 'The verdict starts after 20 finished AI trades. 100+ is much more reliable.';
    final lines = <String>[];
    int points = 0;
    if (n >= 20) {
      points += net > 0 ? 1 : -1;
      points += pf >= 1.2 ? 1 : (pf >= 1.0 ? 0 : -1);
      if (skipN >= 5) points += skipNet < 0 ? 1 : -1;
      if (takenN >= 5) points += (net / n) > (takenNet / takenN) ? 1 : -1;
      if (points >= 3) {
        title = 'GOOD';
        c = p.profit;
      } else if (points >= 1) {
        title = 'OKAY';
        c = p.warning;
      } else {
        title = 'WEAK';
        c = p.loss;
      }
      frac = (points + 4) / 8.0;
      meterLabel = 'AI score';
      meterValue = title;
      meterHint = 'Mixes profit, profit factor, skipped signals and AI vs bot per trade.';
    }
    lines.add('The AI made ${fmtSigned(net)} USDT on $n finished trades (profit factor ${pf.toStringAsFixed(2)}).');
    if (skipN > 0) {
      lines.add(skipNet < 0
          ? 'Signals the AI skipped would have lost ${skipNet.abs().toStringAsFixed(2)} USDT for the bot. Skipping helped.'
          : 'Signals the AI skipped made ${skipNet.toStringAsFixed(2)} USDT for the bot. Skipping cost profit.');
    }
    if (takenN > 0) {
      lines.add('On the signals the AI took, the bot made ${fmtSigned(takenNet)} USDT and the AI made ${fmtSigned(net)} USDT.');
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.cardGap),
      child: _VCard(
        glow: n >= 20 ? c : null,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const _VLabel('IS THE AI HELPING?'),
            const SizedBox(height: 6),
            Text(title, style: TextStyle(color: c, fontSize: 26, fontWeight: FontWeight.w900)),
            const SizedBox(height: 8),
            _meterBar(p, meterLabel, meterValue, frac, c, meterHint),
            for (final l in lines)
              Padding(padding: const EdgeInsets.only(bottom: 4), child: Text(l, style: context.type.metadata.copyWith(color: p.textPrimary, height: 1.4, fontSize: 12))),
            if (n >= 20) Text('Technical: score $points (range -4 to +4).', style: context.type.metadata.copyWith(fontSize: 10.5)),
          ],
        ),
      ),
    );
  }

  // ------------------------------------------------------------------ Live
  Widget _liveTab(AppPalette p, Map<String, dynamic> d) {
    final s = _m(d['summary']);
    final net = _d(s['net']) ?? 0;
    final unreal = _d(s['unrealized']) ?? 0;
    final total = net + unreal;
    final win = _d(s['win_rate']);
    final avg = _d(s['avg']);
    final opens = _l(d['open']).map(_m).toList();
    final waiting = _l(d['decisions']).map(_m).where((x) => x['status'] == 'waiting').toList();
    final queued = (_d(s['queued']) ?? 0).toInt();
    return OWLRefresh(
      onRefresh: _load,
      child: ListView(
        physics: owlPullPhysics,
        padding: _pad,
        children: [
          _banner(p, d),
          _monitorCard(p, d),
          _VCard(
            glow: total >= 0 ? p.profit : p.loss,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const _VLabel('AI VIRTUAL ACCOUNT  ·  NET P&L'),
                const SizedBox(height: 6),
                FittedBox(
                  fit: BoxFit.scaleDown,
                  alignment: Alignment.centerLeft,
                  child: Text('${fmtSigned(total)} USDT', style: context.type.hero.copyWith(color: total >= 0 ? p.profit : p.loss, fontSize: 32)),
                ),
                const SizedBox(height: 4),
                Text('Closed ${fmtSigned(net)}  ·  Open ${fmtSigned(unreal)}  ·  after fees', style: context.type.metadata),
                const SizedBox(height: 14),
                Row(
                  children: [
                    Expanded(child: _VStat('WIN RATE', win == null ? '--' : '${win.toStringAsFixed(1)}%', sub: '${(_d(s['wins']) ?? 0).toInt()} of ${(_d(s['closed']) ?? 0).toInt()} closed')),
                    Expanded(child: _VStat('PER TRADE', avg == null ? '--' : fmtSigned(avg, 3), sub: 'USDT average', color: avg == null ? null : (avg >= 0 ? p.profit : p.loss))),
                    Expanded(child: _VStat('OPEN', '${opens.length}', sub: 'AI trades now')),
                  ],
                ),
                const SizedBox(height: 12),
                Text(_liveStory(s, d), style: context.type.metadata.copyWith(color: p.textPrimary, height: 1.4, fontSize: 12)),
                const SizedBox(height: 12),
                ..._liveMeters(p, s, d),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.cardGap),
          _section('OPEN AI TRADES'),
          if (opens.isEmpty) _empty('No open AI trades.\nWhen the AI takes a bot signal it appears here with its stop, target and live P&L.'),
          for (final t in opens) ...[
            _tradeCard(p, t, d),
            const SizedBox(height: AppSpacing.cardGap),
          ],
          if (waiting.isNotEmpty) ...[
            _section('WAITING FOR A BETTER ENTRY'),
            for (final w in waiting) ...[
              _signalRow(p, w, d),
              const SizedBox(height: AppSpacing.cardGap),
            ],
          ],
          if (queued > 0) Padding(padding: const EdgeInsets.only(top: 4), child: Text('$queued signal${queued == 1 ? '' : 's'} in line for the AI.', style: context.type.metadata)),
        ],
      ),
    );
  }

  Widget _tradeCard(AppPalette p, Map<String, dynamic> t, Map<String, dynamic> d) {
    final buy = t['side'] == 'BUY';
    final pnl = _d(t['pnl']) ?? 0;
    final roi = _d(t['roi']) ?? 0;
    final price = _d(t['price']);
    final entry = _d(t['entry']) ?? 0;
    final sl = _d(t['sl']) ?? 0;
    final tg = _d(t['target']);
    final notes = _l(t['notes']);
    final last = notes.isEmpty ? '' : (_m(notes.last)['text'] ?? '').toString();
    final c = pnl >= 0 ? p.profit : p.loss;
    return OWLPressable(
      pressedScale: 0.99,
      onTap: () => _openDetail(context, _decFor(d, t), t),
      child: _VCard(
        glow: c,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                _SidePill(buy: buy),
                const SizedBox(width: 8),
                Expanded(child: Text((t['symbol'] ?? '').toString(), style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800), overflow: TextOverflow.ellipsis)),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(fmtSigned(pnl), style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: c)),
                    Text('${roi >= 0 ? '+' : ''}${roi.toStringAsFixed(1)}% ROI', style: context.type.metadata.copyWith(color: c, fontSize: 11)),
                  ],
                ),
              ],
            ),
            const SizedBox(height: 12),
            if (tg != null && price != null) _LevelBar(isBuy: buy, stop: sl, entry: entry, target: tg, price: price),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(child: _VStat('ENTRY', _px(entry))),
                Expanded(child: _VStat('NOW', _px(price))),
                Expanded(child: _VStat('STOP', _px(sl), color: p.loss)),
                Expanded(child: _VStat('TARGET', _px(tg), color: p.profit)),
              ],
            ),
            if (last.isNotEmpty) ...[
              const SizedBox(height: 10),
              Text(last, maxLines: 3, overflow: TextOverflow.ellipsis, style: context.type.metadata.copyWith(height: 1.35, color: p.textSecondary)),
            ],
            const SizedBox(height: 6),
            Text('Tap to see the chart and the AI notes', style: context.type.metadata.copyWith(fontSize: 10)),
          ],
        ),
      ),
    );
  }

  Map<String, dynamic>? _decFor(Map<String, dynamic> d, Map<String, dynamic> t) {
    final id = t['dec_id'];
    for (final x in _l(d['decisions'])) {
      final m = _m(x);
      if (m['id'] == id) return m;
    }
    return null;
  }

  // ------------------------------------------------------------------ Signals
  Widget _signalsTab(AppPalette p, Map<String, dynamic> d) {
    var rows = _l(d['decisions']).map(_m).toList();
    if (_filter == 'Taken') rows = rows.where((x) => x['status'] == 'taken').toList();
    if (_filter == 'Skipped') rows = rows.where((x) => x['status'] == 'skipped' || x['status'] == 'expired').toList();
    if (_filter == 'Waiting') rows = rows.where((x) => x['status'] == 'waiting' || x['status'] == 'queued').toList();
    final s = _m(d['summary']);
    return OWLRefresh(
      onRefresh: _load,
      child: ListView(
        physics: owlPullPhysics,
        padding: _pad,
        children: [
          _banner(p, d),
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.s),
            child: Text(
              'Every bot signal and what the Vision AI decided after looking at its chart. '
              '${(_d(s['signals']) ?? 0).toInt()} judged  ·  ${(_d(s['take']) ?? 0).toInt()} taken  ·  ${(_d(s['skip']) ?? 0).toInt()} skipped',
              style: context.type.metadata.copyWith(height: 1.35),
            ),
          ),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: [
                for (final f in const ['All', 'Taken', 'Skipped', 'Waiting'])
                  Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: OWLPressable(
                      pressedScale: 0.97,
                      onTap: () => setState(() => _filter = f),
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                        decoration: BoxDecoration(
                          color: _filter == f ? p.accent.withOpacity(0.16) : p.surfaceHigher,
                          borderRadius: BorderRadius.circular(AppSpacing.radiusPill),
                          border: Border.all(color: _filter == f ? p.accent.withOpacity(0.5) : p.border, width: 0.8),
                        ),
                        child: Text(f, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: _filter == f ? p.accent : p.textMuted)),
                      ),
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.cardGap),
          if (rows.isEmpty) _empty('Nothing here yet.\nNew bot signals appear as soon as the bot opens them.'),
          for (final r in rows) ...[
            _signalRow(p, r, d),
            const SizedBox(height: 10),
          ],
        ],
      ),
    );
  }

  Widget _signalRow(AppPalette p, Map<String, dynamic> r, Map<String, dynamic> d) {
    final st = (r['status'] ?? '').toString();
    final buy = r['side'] == 'BUY';
    final col = _statusColor(p, st);
    final bot = _m(r['bot']);
    final tr = _m(r['trade']);
    final reason = (r['reason'] ?? '').toString();
    final extra = st == 'waiting' && (r['wait_for'] ?? '').toString().isNotEmpty ? 'Waiting for: ${r['wait_for']}' : '';
    final pieces = <String>[];
    if ((r['sig_ist'] ?? '').toString().isNotEmpty) pieces.add(r['sig_ist'].toString());
    pieces.add((r['tf'] ?? '').toString());
    if (bot['state'] == 'closed') pieces.add('Bot: ${fmtSigned(_d(bot['pnl']) ?? 0)}');
    if (bot['state'] == 'open') pieces.add('Bot: open');
    if (tr.isNotEmpty && tr['pnl'] != null) pieces.add('AI: ${fmtSigned(_d(tr['pnl']) ?? 0)}');
    return OWLPressable(
      pressedScale: 0.99,
      onTap: () {
        Map<String, dynamic>? trade;
        final tid = r['trade_id'];
        if (tid != null) {
          for (final x in [..._l(d['open']), ..._l(d['closed'])]) {
            final m = _m(x);
            if (m['id'] == tid) trade = m;
          }
        }
        _openDetail(context, r, trade);
      },
      child: _VCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                _SidePill(buy: buy),
                const SizedBox(width: 8),
                Expanded(child: Text((r['symbol'] ?? '').toString(), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800), overflow: TextOverflow.ellipsis)),
                _Pill(text: _statusLabel(st), color: col),
              ],
            ),
            if (reason.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(reason, maxLines: 2, overflow: TextOverflow.ellipsis, style: context.type.metadata.copyWith(color: p.textPrimary, height: 1.35)),
            ],
            Builder(builder: (context) {
              final ind = _m(r['indicator_summary']);
              final bits = <String>[];
              for (final k in ['ema', 'tsi', 'zscore', 'sd']) {
                final v = (ind[k] ?? '').toString();
                if (v.isNotEmpty) bits.add(v);
              }
              if (bits.isEmpty) return const SizedBox.shrink();
              return Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(bits.take(2).join(' · '), maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: context.type.metadata.copyWith(fontSize: 11, color: p.textSecondary)),
              );
            }),
            if (extra.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(extra, style: context.type.metadata.copyWith(color: p.warning)),
            ],
            const SizedBox(height: 8),
            Text(pieces.where((e) => e.isNotEmpty).join('  ·  '), style: context.type.metadata.copyWith(fontSize: 11)),
          ],
        ),
      ),
    );
  }

  // ------------------------------------------------------------------ Results
  Widget _resultsTab(AppPalette p, Map<String, dynamic> d) {
    final s = _m(d['summary']);
    final taken = _m(s['bot_on_taken']);
    final skipped = _m(s['bot_on_skipped']);
    final closed = _l(d['closed']).map(_m).toList();
    final net = _d(s['net']) ?? 0;
    final skipNet = _d(skipped['net']) ?? 0;
    final skipN = (_d(skipped['n']) ?? 0).toInt();
    String verdict;
    if (skipN == 0) {
      verdict = 'No skipped signal has a finished bot result yet.';
    } else if (skipNet < 0) {
      verdict = 'On the $skipN signals the AI skipped, the bot lost ${skipNet.abs().toStringAsFixed(2)} USDT. Skipping them helped.';
    } else {
      verdict = 'On the $skipN signals the AI skipped, the bot made ${skipNet.toStringAsFixed(2)} USDT. Skipping them cost profit.';
    }
    return OWLRefresh(
      onRefresh: _load,
      child: ListView(
        physics: owlPullPhysics,
        padding: _pad,
        children: [
          _banner(p, d),
          _verdictCard(p, d),
          _VCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const _VLabel('DETAILS: AI vs BOT'),
                const SizedBox(height: 10),
                _scoreRow(p, 'AI trades (its own exits)', '${(_d(s['closed']) ?? 0).toInt()} closed', net),
                const Divider(height: 18),
                _scoreRow(p, 'Bot on the signals the AI took', '${(_d(taken['n']) ?? 0).toInt()} closed', _d(taken['net']) ?? 0),
                const Divider(height: 18),
                _scoreRow(p, 'Bot on the signals the AI skipped', '$skipN closed  ·  W ${(_d(skipped['wins']) ?? 0).toInt()} / L ${(_d(skipped['losses']) ?? 0).toInt()}', skipNet),
                const SizedBox(height: 12),
                Text(verdict, style: context.type.metadata.copyWith(color: p.textPrimary, height: 1.4)),
                const SizedBox(height: 8),
                Text('A few trades prove nothing. Judge the AI after a large number of signals.', style: context.type.metadata.copyWith(fontSize: 11, height: 1.35)),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.cardGap),
          _indicatorUseCard(p, d),
          const SizedBox(height: AppSpacing.cardGap),
          _section('CLOSED AI TRADES'),
          if (closed.isEmpty) _empty('No closed AI trades yet.'),
          for (final t in closed) ...[
            _closedRow(p, t, d),
            const SizedBox(height: 10),
          ],
        ],
      ),
    );
  }

  Widget _indicatorUseCard(AppPalette p, Map<String, dynamic> d) {
    final u = _m(d['indicator_use']);
    final n = (_d(u['n']) ?? 0).toInt();
    if (n == 0) {
      return _VCard(
        child: Text('Indicator check: no judged signal yet. After the first AI decision this shows if it reads both the EMA/SD chart and the TSI/Z-score panes.',
            style: context.type.metadata.copyWith(height: 1.4)),
      );
    }
    String pct(String k) => '${(((_d(u[k]) ?? 0) * 100) / n).round()}%';
    final both = (((_d(u['both']) ?? 0) * 100) / n).round();
    return _VCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _VLabel('DOES THE AI READ BOTH INDICATORS?'),
          const SizedBox(height: 10),
          Text('Of the last $n judged signals, the AI answered:', style: context.type.metadata.copyWith(color: p.textPrimary, height: 1.35)),
          const SizedBox(height: 6),
          Text('EMA ${pct('ema')}  ·  SD bands ${pct('sd')}  ·  TSI ${pct('tsi')}  ·  Z-score ${pct('zscore')}',
              style: TextStyle(color: p.textPrimary, fontWeight: FontWeight.w700, fontSize: 13)),
          const SizedBox(height: 6),
          Text(both >= 80
              ? 'Good: $both% of decisions used the chart AND the lower panes.'
              : 'Only $both% of decisions used the chart AND the lower panes. Check the reasons on the Signals tab.',
              style: context.type.metadata.copyWith(height: 1.35)),
        ],
      ),
    );
  }

  Widget _scoreRow(AppPalette p, String title, String sub, double v) {
    return Row(
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700)),
              const SizedBox(height: 2),
              Text(sub, style: context.type.metadata.copyWith(fontSize: 11)),
            ],
          ),
        ),
        Text('${fmtSigned(v)} USDT', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: v >= 0 ? p.profit : p.loss)),
      ],
    );
  }

  Widget _closedRow(AppPalette p, Map<String, dynamic> t, Map<String, dynamic> d) {
    final pnl = _d(t['pnl']) ?? 0;
    final c = pnl >= 0 ? p.profit : p.loss;
    return OWLPressable(
      pressedScale: 0.99,
      onTap: () => _openDetail(context, _decFor(d, t), t),
      child: _VCard(
        child: Row(
          children: [
            _SidePill(buy: t['side'] == 'BUY'),
            const SizedBox(width: 8),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text((t['symbol'] ?? '').toString(), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w800)),
                  const SizedBox(height: 2),
                  Text((t['exit_reason'] ?? '').toString(), maxLines: 2, overflow: TextOverflow.ellipsis, style: context.type.metadata.copyWith(fontSize: 11, height: 1.3)),
                ],
              ),
            ),
            const SizedBox(width: 8),
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(fmtSigned(pnl), style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: c)),
                Text('${(_d(t['roi']) ?? 0).toStringAsFixed(1)}% ROI', style: context.type.metadata.copyWith(fontSize: 10, color: c)),
              ],
            ),
          ],
        ),
      ),
    );
  }

  // ------------------------------------------------------------------ Guide
  Widget _guideTab(AppPalette p) {
    final g = _guide;
    return ListView(
      physics: owlPullPhysics,
      padding: _pad,
      children: [
        Text(
          'This is what the Vision AI is told about your indicators before it looks at any chart. '
          'If something is wrong or missing, write it in your notes below. The AI reads your notes together with this guide.',
          style: context.type.metadata.copyWith(height: 1.4),
        ),
        const SizedBox(height: AppSpacing.cardGap),
        _VCard(
          child: g == null
              ? const Center(child: Padding(padding: EdgeInsets.all(12), child: CircularProgressIndicator(strokeWidth: 2)))
              : SelectableText((g['guide'] ?? '').toString(), style: context.type.metadata.copyWith(color: p.textPrimary, height: 1.45, fontSize: 12.5)),
        ),
        const SizedBox(height: AppSpacing.cardGap),
        const _VLabel('YOUR NOTES'),
        const SizedBox(height: 8),
        TextField(
          controller: _notes,
          minLines: 4,
          maxLines: 10,
          maxLength: 4000,
          decoration: InputDecoration(
            hintText: 'Example: When Z is green but the black line is above it, treat the line as resistance.',
            filled: true,
            fillColor: p.surfaceHigher,
            border: OutlineInputBorder(borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), borderSide: BorderSide(color: p.border)),
          ),
        ),
        const SizedBox(height: 8),
        SizedBox(
          width: double.infinity,
          child: ElevatedButton(
            onPressed: _saving ? null : _saveNotes,
            child: Text(_saving ? 'Saving...' : 'Save notes'),
          ),
        ),
      ],
    );
  }

  // ------------------------------------------------------------------ detail sheet
  void _openDetail(BuildContext context, Map<String, dynamic>? dec, Map<String, dynamic>? trade) {
    AppHaptics.light();
    final p = context.palette;
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: p.surfaceElevated,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.92,
        minChildSize: 0.5,
        maxChildSize: 0.97,
        builder: (ctx, scroll) => _DetailSheet(dec: dec, trade: trade, controller: scroll),
      ),
    );
  }
}

// ======================================================================== detail sheet
class _DetailSheet extends StatelessWidget {
  final Map<String, dynamic>? dec;
  final Map<String, dynamic>? trade;
  final ScrollController controller;
  const _DetailSheet({required this.dec, required this.trade, required this.controller});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final src = trade ?? dec ?? <String, dynamic>{};
    final buy = src['side'] == 'BUY';
    final st = (dec?['status'] ?? (trade != null ? 'taken' : '')).toString();
    final reason = (dec?['reason'] ?? '').toString();
    final checks = <MapEntry<String, String>>[];
    final cl = _m(dec?['checklist']);
    cl.forEach((k, v) => checks.add(MapEntry(k, v.toString())));
    final cl2 = _m(trade?['last_checklist']);
    final hasReview = cl2.isNotEmpty;
    final notes = _l(trade?['notes']);
    final open = trade != null && trade!['status'] == 'open';
    final pnl = _d(trade?['pnl']);
    final entry = trade != null ? _d(trade!['entry']) : _d(dec?['sig_price']);
    final stop = trade != null ? _d(trade!['sl']) : _d(dec?['stop']);
    final target = trade != null ? _d(trade!['target']) : _d(dec?['target']);
    final decId = (dec?['id'] ?? '').toString();
    final trId = (trade?['id'] ?? '').toString();
    return ListView(
      controller: controller,
      padding: const EdgeInsets.fromLTRB(AppSpacing.l, 10, AppSpacing.l, 32),
      children: [
        Center(child: Container(width: 40, height: 4, decoration: BoxDecoration(color: p.border, borderRadius: BorderRadius.circular(2)))),
        const SizedBox(height: 14),
        Row(
          children: [
            _SidePill(buy: buy),
            const SizedBox(width: 8),
            Expanded(child: Text((src['symbol'] ?? '').toString(), style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800))),
            if (st.isNotEmpty) _Pill(text: _statusLabel(st), color: _statusColor(p, st)),
          ],
        ),
        const SizedBox(height: 12),
        if (reason.isNotEmpty) Text(reason, style: context.type.metadata.copyWith(color: p.textPrimary, fontSize: 14, height: 1.4)),
        // Indicator summary (EMA/SD + TSI/Z) — both families, for the owner on chevron/detail
        Builder(builder: (context) {
          final ind = _m(dec?['indicator_summary']);
          final ctx = (dec?['recent_context'] ?? '').toString();
          if (ind.isEmpty && ctx.isEmpty) return const SizedBox.shrink();
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 12),
              const _VLabel('INDICATORS AT ENTRY (BOTH FAMILIES)'),
              const SizedBox(height: 6),
              if (ind['ema'] != null && ind['ema'].toString().isNotEmpty)
                _checkRow(context, 'ema', ind['ema'].toString()),
              if (ind['sd'] != null && ind['sd'].toString().isNotEmpty)
                _checkRow(context, 'sd', ind['sd'].toString()),
              if (ind['tsi'] != null && ind['tsi'].toString().isNotEmpty)
                _checkRow(context, 'tsi', ind['tsi'].toString()),
              if (ind['zscore'] != null && ind['zscore'].toString().isNotEmpty)
                _checkRow(context, 'zscore', ind['zscore'].toString()),
              if (ind['align'] != null && ind['align'].toString().isNotEmpty)
                _checkRow(context, 'align', ind['align'].toString()),
              if (ctx.isNotEmpty) ...[
                const SizedBox(height: 8),
                Text(ctx, style: context.type.metadata.copyWith(color: p.textPrimary, height: 1.35, fontSize: 12)),
              ],
            ],
          );
        }),
        const SizedBox(height: 14),
        Row(
          children: [
            Expanded(child: _VStat(trade != null ? 'ENTRY' : 'SIGNAL PRICE', _px(entry))),
            Expanded(child: _VStat('STOP', _px(stop), color: p.loss)),
            Expanded(child: _VStat('TARGET', _px(target), color: p.profit)),
            if (pnl != null) Expanded(child: _VStat(open ? 'OPEN P&L' : 'RESULT', fmtSigned(pnl), color: pnl >= 0 ? p.profit : p.loss)),
          ],
        ),
        if (trade != null && trade!['status'] == 'closed' && (trade!['exit_reason'] ?? '').toString().isNotEmpty) ...[
          const SizedBox(height: 10),
          Text('Closed: ${trade!['exit_reason']}', style: context.type.metadata.copyWith(height: 1.35)),
        ],
        const SizedBox(height: 16),
        _ChartBox(decId: decId, tradeId: trId),
        if (checks.isNotEmpty) ...[
          const SizedBox(height: 18),
          const _VLabel('WHAT THE AI SAW AT THE SIGNAL'),
          const SizedBox(height: 8),
          for (final c in checks) _checkRow(context, c.key, c.value),
        ],
        if (hasReview) ...[
          const SizedBox(height: 18),
          const _VLabel('LATEST CHECK ON THE OPEN TRADE'),
          const SizedBox(height: 8),
          for (final e in cl2.entries) _checkRow(context, e.key, e.value.toString()),
        ],
        if (notes.isNotEmpty) ...[
          const SizedBox(height: 18),
          const _VLabel('AI NOTES'),
          const SizedBox(height: 8),
          for (final n in notes.reversed)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SizedBox(width: 46, child: Text(_hm(_m(n)['t']), style: context.type.metadata.copyWith(fontSize: 11))),
                  Expanded(child: Text((_m(n)['text'] ?? '').toString(), style: context.type.metadata.copyWith(color: p.textPrimary, height: 1.35))),
                ],
              ),
            ),
        ],
      ],
    );
  }

  Widget _checkRow(BuildContext context, String k, String v) {
    final name = _checkNames[k] ?? (k.isEmpty ? k : k[0].toUpperCase() + k.substring(1));
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(width: 92, child: Text(name, style: context.type.metadata.copyWith(fontWeight: FontWeight.w700))),
          Expanded(child: Text(v, style: context.type.metadata.copyWith(color: context.palette.textPrimary, height: 1.35))),
        ],
      ),
    );
  }
}

class _ChartBox extends StatefulWidget {
  final String decId;
  final String tradeId;
  const _ChartBox({required this.decId, required this.tradeId});

  @override
  State<_ChartBox> createState() => _ChartBoxState();
}

class _ChartBoxState extends State<_ChartBox> {
  bool _live = false;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final prov = context.read<AppProvider>();
    final hasSaved = widget.decId.isNotEmpty;
    final liveId = widget.tradeId.isNotEmpty ? widget.tradeId : widget.decId;
    final showLive = _live || !hasSaved;
    final id = showLive ? liveId : widget.decId;
    final url = prov.visionImageUrl(id, live: showLive);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            if (hasSaved) _chip(p, 'Chart the AI saw', !showLive, () => setState(() => _live = false)),
            if (hasSaved) const SizedBox(width: 8),
            _chip(p, 'Live chart with stop and target', showLive, () => setState(() => _live = true)),
          ],
        ),
        const SizedBox(height: 10),
        ClipRRect(
          borderRadius: BorderRadius.circular(12),
          child: Container(
            color: Colors.white,
            child: InteractiveViewer(
              minScale: 1,
              maxScale: 4,
              child: Image.network(
                url,
                key: ValueKey(url),
                fit: BoxFit.fitWidth,
                width: double.infinity,
                loadingBuilder: (c, child, prog) => prog == null
                    ? child
                    : const SizedBox(height: 260, child: Center(child: CircularProgressIndicator(strokeWidth: 2))),
                errorBuilder: (c, e, s) => const SizedBox(
                  height: 160,
                  child: Center(child: Text('Chart not available yet.', style: TextStyle(color: Colors.black54))),
                ),
              ),
            ),
          ),
        ),
        const SizedBox(height: 6),
        Text('Pinch to zoom. The chart is drawn by the backend from the same candles and indicators the AI used.', style: context.type.metadata.copyWith(fontSize: 10)),
      ],
    );
  }

  Widget _chip(AppPalette p, String text, bool on, VoidCallback tap) {
    return OWLPressable(
      pressedScale: 0.97,
      onTap: tap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: on ? p.accent.withOpacity(0.16) : p.surfaceHigher,
          borderRadius: BorderRadius.circular(AppSpacing.radiusPill),
          border: Border.all(color: on ? p.accent.withOpacity(0.5) : p.border, width: 0.8),
        ),
        child: Text(text, style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: on ? p.accent : p.textMuted)),
      ),
    );
  }
}

// ======================================================================== small pieces
class _VCard extends StatelessWidget {
  final Widget child;
  final Color? glow;
  const _VCard({required this.child, this.glow});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium + 2),
        border: Border.all(color: glow != null ? glow!.withOpacity(0.45) : p.border, width: 1),
        boxShadow: glow == null ? null : [BoxShadow(color: glow!.withOpacity(0.10), blurRadius: 18)],
      ),
      child: child,
    );
  }
}

class _VLabel extends StatelessWidget {
  final String text;
  const _VLabel(this.text);
  @override
  Widget build(BuildContext context) =>
      Text(text, style: context.type.metadata.copyWith(fontSize: 10, fontWeight: FontWeight.w700, letterSpacing: 0.7));
}

class _VStat extends StatelessWidget {
  final String label;
  final String value;
  final String? sub;
  final Color? color;
  const _VStat(this.label, this.value, {this.sub, this.color});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _VLabel(label),
        const SizedBox(height: 3),
        FittedBox(
          fit: BoxFit.scaleDown,
          alignment: Alignment.centerLeft,
          child: Text(value, style: TextStyle(color: color ?? p.textPrimary, fontWeight: FontWeight.w800, fontSize: 14)),
        ),
        if (sub != null) Text(sub!, style: context.type.metadata.copyWith(fontSize: 10)),
      ],
    );
  }
}

class _Pill extends StatelessWidget {
  final String text;
  final Color color;
  const _Pill({required this.text, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
      decoration: BoxDecoration(
        color: color.withOpacity(0.14),
        borderRadius: BorderRadius.circular(AppSpacing.radiusPill),
        border: Border.all(color: color.withOpacity(0.4), width: 0.8),
      ),
      child: Text(text, style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w800, color: color, letterSpacing: 0.4)),
    );
  }
}

class _SidePill extends StatelessWidget {
  final bool buy;
  const _SidePill({required this.buy});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final c = buy ? p.profit : p.loss;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(color: c, borderRadius: BorderRadius.circular(6)),
      child: Text(buy ? 'LONG' : 'SHORT', style: const TextStyle(fontSize: 10.5, fontWeight: FontWeight.w800, color: Colors.white)),
    );
  }
}

/// Stop ... entry ... target with the live price on it, so you can see at a glance where the trade stands.
class _LevelBar extends StatelessWidget {
  final bool isBuy;
  final double stop;
  final double entry;
  final double target;
  final double price;
  const _LevelBar({required this.isBuy, required this.stop, required this.entry, required this.target, required this.price});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final lo = stop < target ? stop : target;
    final hi = stop < target ? target : stop;
    final span = (hi - lo) == 0 ? 1.0 : (hi - lo);
    double frac(double v) => ((v - lo) / span).clamp(0.0, 1.0).toDouble();
    final leftIsStop = stop < target;
    final colors = leftIsStop ? [p.loss.withOpacity(0.55), p.profit.withOpacity(0.55)] : [p.profit.withOpacity(0.55), p.loss.withOpacity(0.55)];
    return LayoutBuilder(
      builder: (context, box) {
        final w = box.maxWidth;
        return SizedBox(
          height: 26,
          child: Stack(
            children: [
              Positioned(
                left: 0,
                right: 0,
                top: 10,
                height: 6,
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(3),
                    gradient: LinearGradient(colors: colors),
                  ),
                ),
              ),
              Positioned(left: w * frac(entry) - 1, top: 6, width: 2, height: 14, child: Container(color: p.textMuted)),
              Positioned(
                left: w * frac(price) - 7,
                top: 6,
                child: Container(
                  width: 14,
                  height: 14,
                  decoration: BoxDecoration(color: p.accent, shape: BoxShape.circle, border: Border.all(color: Colors.white, width: 2)),
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}
