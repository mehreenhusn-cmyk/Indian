import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';
import '../widgets/ai_chat_popup.dart';
import '../widgets/ai_ab_card.dart';
import '../widgets/ai_versus_card.dart';
import '../widgets/trade_chart.dart';
import '../widgets/ai_verdict_card.dart';
import '../widgets/ai_trail_card.dart';
import '../widgets/ai_trail_trades_card.dart';
import '../widgets/ai_own_card.dart';
import '../widgets/ai_tab_summary.dart';
import '../widgets/ai_learning_card.dart';
import '../widgets/owl_eye_dot.dart';
import '../widgets/owl_card.dart';
import '../widgets/owl_empty_state.dart';
import '../widgets/owl_status_pill.dart';
import '../widgets/owl_pressable.dart';
import '../widgets/owl_refresh.dart';
import '../widgets/ai_story_card.dart';
import 'ai_insights_screen.dart';

/// The AI tab: everything the AI learns from, in one place.
///   Overview   - the simple story first (where the strategy loses / earns), then ALL-TIME numbers (net P&L, win rate, break-even meter,
///                daily bars, exit reasons) + a plain-language verdict.
///   Insights   - the existing pattern screen (story card on top, details behind a button).
///   Trades     - every bot trade with the AI copy beside it (who left where).
///   Bot vs AI  - the scoreboard, ready meter, skips and day plan.
/// All numbers come from the backend (ai_book.py / ai_stats.py), computed from
/// real closed trades (the exchange fee is already inside every P&L). Nothing is
/// calculated or guessed on the phone. The floating "Ask AI" button opens the
/// same assistant (same saved chat) as a small popup.
const _kindNames = {
  'direction': 'Direction',
  'session': 'Session',
  'zone': 'SD zone',
  'timeframe': 'Timeframe',
  'sl_dist': 'SL distance',
  'volume': 'Volume',
  'ema': 'EMA slope',
  'hour': 'Entry hour (IST)',
};

/// true = simple AI tab: Overview (short), a simple Insights (verdict + checklist), Trade Book and Bot vs AI (Desk). The hidden screens
/// (Insights, Learning and the long Overview cards) are NOT deleted - set this to false to get them all back.
const bool _kSimpleAi = true;

class AiTabScreen extends StatefulWidget {
  const AiTabScreen({super.key});

  @override
  State<AiTabScreen> createState() => _AiTabScreenState();
}

class _AiTabScreenState extends State<AiTabScreen> with SingleTickerProviderStateMixin {
  // The open sub-tab is remembered while the app runs, so coming back to the AI tab
  // shows the sub-tab you left (not always the first one).
  static int _lastSubTab = 0;
  late final TabController _tabs = TabController(length: 7, vsync: this, initialIndex: _lastSubTab.clamp(0, 6));
  final ScrollController _stripCtl = ScrollController();
  Map<String, dynamic>? _summary;
  bool _failed = false;
  Timer? _timer;
  @override
  void initState() {
    super.initState();
    _tabs.addListener(() {
      _lastSubTab = _tabs.index;
      if (mounted) setState(() {});
      _revealChip();
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_stripCtl.hasClients) return;
      _stripCtl.jumpTo((_tabs.index * 82.0 - 60).clamp(0.0, _stripCtl.position.maxScrollExtent).toDouble());
    });
    final cached = context.read<AppProvider>().peekAiBook() ?? context.read<AppProvider>().peekAi('/api/ai/book');
    if (cached != null && cached['summary'] is Map) {
      _summary = Map<String, dynamic>.from(cached['summary'] as Map); // old numbers at once, fresh ones behind
    }
    _load();
    _timer = Timer.periodic(const Duration(seconds: 90), (_) => _load()); // 90s (was 30s): the phone has little CPU
  }

  Future<void> _load() async {
    final r = await context.read<AppProvider>().fetchAiBook(offset: 0, limit: 1);
    if (!mounted) return;
    setState(() {
      if (r != null && r['summary'] is Map) {
        _summary = Map<String, dynamic>.from(r['summary'] as Map);
        _failed = false;
      } else if (_summary == null) {
        _failed = true;
      }
    });
  }

  /// Keeps the open tab's chip inside the visible part of the strip.
  void _revealChip() {
    if (!_stripCtl.hasClients) return;
    final want = (_tabs.index * 82.0 - 60).clamp(0.0, _stripCtl.position.maxScrollExtent).toDouble();
    _stripCtl.animateTo(want, duration: const Duration(milliseconds: 200), curve: Curves.easeOut);
  }

  @override
  void dispose() {
    _timer?.cancel();
    _stripCtl.dispose();
    _tabs.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
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
                  OwlEyeDot(live: _summary != null, color: p.owlEye, size: 8),
                  const SizedBox(width: 8),
                  Text('AI', style: context.type.hero.copyWith(fontSize: 22, fontWeight: FontWeight.w800)),
                  const Spacer(),
                  Text('asli closed trades', style: context.type.metadata),
                ],
              ),
            ),
            _segmented(context, p),
            const SizedBox(height: 4),
            Expanded(
              child: TabBarView(
                controller: _tabs,
                children: [
                  _Overview(
                    summary: _summary,
                    failed: _failed,
                    onRefresh: _load,
                    onMore: null,
                    onHour: null,
                    tabs: _tabs,
                  ),
                  // 1 Trail: does another trailing stop beat the bot's? (result first, details below)
                  ListView(
                    physics: owlPullPhysics,
                    padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.s, AppSpacing.l, 96),
                    children: [
                      AiTrailSummary(tabs: _tabs, tabIndex: 1),
                      AiTrailCard(tabs: _tabs, tabIndex: 1),
                      const SizedBox(height: AppSpacing.cardGap),
                      AiTrailTradesCard(tabs: _tabs, tabIndex: 1),
                    ],
                  ),
                  // 2 Bot vs AI: the AI's choices (take / skip / wait) next to what the bot did
                  AiVersusCard(tabs: _tabs, tabIndex: 2, part: 'summary', header: AiVersusSummary(tabs: _tabs, tabIndex: 2)),
                  // 3 Trades: every bot trade with the AI copy beside it
                  AiVersusCard(tabs: _tabs, tabIndex: 3, part: 'trades'),
                  // 4 Free AI: its own trades, nothing wired to the bot
                  ListView(
                    physics: owlPullPhysics,
                    padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.s, AppSpacing.l, 96),
                    children: [
                      AiFreeSummary(tabs: _tabs, tabIndex: 4),
                      AiOwnCard(tabs: _tabs, tabIndex: 4),
                    ],
                  ),
                  // 5 Learned: what the AI found about the indicators, by counting only
                  ListView(
                    physics: owlPullPhysics,
                    padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.s, AppSpacing.l, 96),
                    children: [AiLearnedCard(tabs: _tabs, tabIndex: 5)],
                  ),
                  // 6 Filter test (the older A/B research)
                  _kSimpleAi ? AiVerdictCard(tabs: _tabs, tabIndex: 6) : AiInsightsScreen(embedded: true),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _segmented(BuildContext context, AppPalette p) {
    const labels = ['Bot', 'Trail', 'Bot vs AI', 'Trades', 'Free AI', 'Learned', 'Filter test'];
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: AppSpacing.l),
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        color: p.surfaceHigher,
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
        border: Border.all(color: p.border, width: 0.6),
      ),
      child: SingleChildScrollView(
        controller: _stripCtl,
        scrollDirection: Axis.horizontal,
        child: Row(
          children: [
            for (var i = 0; i < labels.length; i++)
              OWLPressable(
                pressedScale: 0.97,
                onTap: () {
                  AppHaptics.light();
                  _tabs.index = i; // straight jump: no slide through the tabs in between
                },
                child: AnimatedContainer(
                  duration: AppMotion.base,
                  padding: const EdgeInsets.symmetric(vertical: 9, horizontal: 13),
                  decoration: BoxDecoration(
                    color: _tabs.index == i ? p.accent.withOpacity(0.16) : Colors.transparent,
                    borderRadius: BorderRadius.circular(AppSpacing.radiusSmall + 1),
                  ),
                  alignment: Alignment.center,
                  child: Text(
                    labels[i],
                    style: TextStyle(
                      fontSize: 11.5,
                      fontWeight: _tabs.index == i ? FontWeight.w800 : FontWeight.w500,
                      color: _tabs.index == i ? p.accent : p.textMuted,
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

// ----------------------------------------------------------------- helpers --

double _d(dynamic v) => (v is num) ? v.toDouble() : 0.0;
int _i(dynamic v) => (v is num) ? v.toInt() : 0;

const _mon = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/// Binance day (00:00 UTC == 5:30 AM IST) of a unix timestamp.
DateTime? _utcDay(dynamic ts) {
  final v = numOrNull(ts);
  if (v == null) return null;
  final d = DateTime.fromMillisecondsSinceEpoch((v * 1000).round(), isUtc: true);
  return DateTime.utc(d.year, d.month, d.day);
}

String _istHm(dynamic ts) {
  final v = numOrNull(ts);
  if (v == null) return '--';
  final d = DateTime.fromMillisecondsSinceEpoch((v * 1000).round(), isUtc: true).add(const Duration(hours: 5, minutes: 30));
  return '${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';
}

String _dayTitle(DateTime d) {
  final n = DateTime.now().toUtc();
  final today = DateTime.utc(n.year, n.month, n.day);
  if (d == today) return 'Today';
  if (d == today.subtract(const Duration(days: 1))) return 'Yesterday';
  return '${d.day} ${_mon[d.month - 1]}';
}

String _ymdShort(String ymd) {
  final p = ymd.split('-');
  if (p.length != 3) return ymd;
  final m = (int.tryParse(p[1]) ?? 1).clamp(1, 12);
  return '${int.tryParse(p[2]) ?? p[2]} ${_mon[m - 1]}';
}

class _Card extends StatelessWidget {
  final Widget child;
  final Color? glow;
  final EdgeInsets padding;
  const _Card({required this.child, this.glow, this.padding = const EdgeInsets.all(14)});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Container(
      width: double.infinity,
      padding: padding,
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium + 2),
        border: Border.all(color: glow != null ? glow!.withOpacity(0.45) : p.border, width: 1),
        boxShadow: glow == null ? null : [BoxShadow(color: glow!.withOpacity(0.10), blurRadius: 18, spreadRadius: 0)],
      ),
      child: child,
    );
  }
}

class _Label extends StatelessWidget {
  final String text;
  const _Label(this.text);
  @override
  Widget build(BuildContext context) =>
      Text(text, style: context.type.metadata.copyWith(fontSize: 10, fontWeight: FontWeight.w700, letterSpacing: 0.7));
}

class _Stat extends StatelessWidget {
  final String label;
  final String value;
  final String? sub;
  final Color? color;
  const _Stat(this.label, this.value, {this.sub, this.color});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _Label(label),
        const SizedBox(height: 3),
        FittedBox(
          fit: BoxFit.scaleDown,
          alignment: Alignment.centerLeft,
          child: Text(value, style: AppTypography.primaryData.copyWith(color: color ?? p.textPrimary, fontWeight: FontWeight.w800, fontSize: 16)),
        ),
        if (sub != null) Text(sub!, style: context.type.metadata.copyWith(fontSize: 10)),
      ],
    );
  }
}

// ----------------------------------------------------------------- overview --

class _Overview extends StatelessWidget {
  final Map<String, dynamic>? summary;
  final bool failed;
  final Future<void> Function() onRefresh;
  final void Function(int hour)? onHour;
  final VoidCallback? onMore;
  final TabController? tabs; // the trailing card only loads / refreshes while Overview is the open tab
  const _Overview({required this.summary, required this.failed, required this.onRefresh, this.onHour, this.onMore, this.tabs});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final s = summary;
    if (s == null) {
      return OWLRefresh(
        onRefresh: onRefresh,
        child: OWLPullEmpty(
          child: OwlLoading(failed: failed),
        ),
      );
    }
    final n = _i(s['n']);
    if (n == 0) {
      return OWLRefresh(
        onRefresh: onRefresh,
        child: OWLPullEmpty(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Text('Abhi koi closed trade nahi. Pehla trade band hote hi yahan poora hisaab dikhega.',
                textAlign: TextAlign.center, style: context.type.secondary.copyWith(color: p.textMuted)),
          ),
        ),
      );
    }

    final net = _d(s['net']);
    final win = net >= 0 ? p.profit : p.loss;
    final winRate = _d(s['win_rate']);
    final be = s['breakeven_wr'] is num ? _d(s['breakeven_wr']) : null;
    final pf = s['profit_factor'] is num ? _d(s['profit_factor']) : null;
    final today = (s['today'] is Map) ? Map<String, dynamic>.from(s['today'] as Map) : <String, dynamic>{};
    final tPnl = _d(today['pnl']);
    final days = (s['days'] is List) ? List<Map<String, dynamic>>.from((s['days'] as List).map((e) => Map<String, dynamic>.from(e as Map))) : <Map<String, dynamic>>[];
    final reasons = (s['reasons'] is List) ? List<Map<String, dynamic>>.from((s['reasons'] as List).map((e) => Map<String, dynamic>.from(e as Map))) : <Map<String, dynamic>>[];
    final verdict = (s['verdict'] is List) ? List<String>.from((s['verdict'] as List).map((e) => '$e')) : <String>[];
    final minSample = _i(s['min_sample']);
    final eq = (s['equity'] is List) ? s['equity'] as List : const [];
    final health = (s['health'] is Map) ? Map<String, dynamic>.from(s['health'] as Map) : null;
    final hours = (s['hours'] is List) ? s['hours'] as List : const [];

    return OWLRefresh(
      onRefresh: onRefresh,
      child: ListView(
        physics: owlPullPhysics,
        padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.s, AppSpacing.l, 96),
        children: [
          // ---- the simple story: where the strategy loses / earns ----
          if (!_kSimpleAi) ...[
            AiStoryCard(compact: true, onMore: onMore),
            const SizedBox(height: AppSpacing.cardGap),
          ],

          // ---- who this tab is about ----
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.s),
            child: Text(
              'BOT results: every closed trade the bot took. The AI\'s own trades are in the Bot vs AI and Free AI tabs.',
              style: context.type.metadata.copyWith(height: 1.35),
            ),
          ),

          // ---- hero: all-time net ----
          _Card(
            glow: win,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(children: [
                  const Expanded(child: _Label('BOT  ·  ALL-TIME NET P&L')),
                  // UI4b: one clear status chip. Too few trades = amber, else green / red by the net result.
                  OWLStatusPill(
                    text: n < minSample ? 'TOO EARLY' : (net >= 0 ? 'IN PROFIT' : 'IN LOSS'),
                    color: n < minSample ? p.warning : win,
                    showDot: false,
                  ),
                ]),
                const SizedBox(height: 6),
                TweenAnimationBuilder<double>(
                  tween: Tween<double>(begin: 0, end: net),
                  duration: const Duration(milliseconds: 700),
                  curve: Curves.easeOutCubic,
                  builder: (_, v, __) => FittedBox(
                    fit: BoxFit.scaleDown,
                    alignment: Alignment.centerLeft,
                    child: Text('${fmtSigned(v)} USDT', style: context.type.hero.copyWith(color: win, fontSize: 36)),
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  '$n trades',
                  style: context.type.metadata,
                ),
                const SizedBox(height: 14),
                Row(
                  children: [
                    Expanded(child: _Stat('WIN RATE', '${winRate.toStringAsFixed(1)}%', sub: 'W ${_i(s['wins'])} / L ${_i(s['losses'])}')),
                    Expanded(
                      child: _Stat('HAR TRADE', fmtSigned(_d(s['expectancy']), 3),
                          sub: 'USDT average', color: _d(s['expectancy']) >= 0 ? p.profit : p.loss),
                    ),
                    Expanded(
                      child: _Stat('PROFIT FACTOR', pf == null ? '--' : pf.toStringAsFixed(2),
                          sub: pf == null ? 'koi haar nahi' : (pf >= 1 ? '1 se upar = theek' : '1 se neeche = loss'),
                          color: pf == null ? null : (pf >= 1 ? p.profit : p.loss)),
                    ),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.cardGap),

          // ---- today vs all-time ----
          Row(
            children: [
              Expanded(
                child: _Card(
                  child: _Stat('AAJ', '${_i(today['n'])} trades',
                      sub: '${fmtSigned(tPnl)} USDT  ·  ${_i(today['wins'])} jeet', color: null),
                ),
              ),
              const SizedBox(width: AppSpacing.cardGap),
              Expanded(
                child: _Card(child: _Stat('TOTAL', '$n trades', sub: 'ab tak, sab milake')),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.cardGap),

          // ---- running P&L line ----
          if (eq.length >= 2) ...[
            _Card(child: _equityCard(context, p, eq)),
            const SizedBox(height: AppSpacing.cardGap),
          ],

          // ---- break-even meter ----
          if (be != null && !_kSimpleAi) ...[
            _Card(child: _breakEven(context, p, winRate, be, _d(s['avg_win']), _d(s['avg_loss']))),
            const SizedBox(height: AppSpacing.cardGap),
          ],

          // ---- health (screen only - the AI never reads this) ----
          if (health != null && !_kSimpleAi) ...[
            _Card(child: _healthCard(context, p, health)),
            const SizedBox(height: AppSpacing.cardGap),
          ],

          // ---- ML shadow hit-rate (owner only - never sent to the AI) ----
          if (!_kSimpleAi) ...[
            const _ShadowCard(),
            const SizedBox(height: AppSpacing.cardGap),
          ],

          // ---- verdict ----
          if (!_kSimpleAi) ...[
          _Card(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(children: [
                  Icon(Icons.auto_awesome_rounded, size: 15, color: p.purple),
                  const SizedBox(width: 6),
                  const _Label('AI VERDICT'),
                ]),
                const SizedBox(height: 8),
                for (final line in verdict)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Padding(
                          padding: const EdgeInsets.only(top: 6, right: 8),
                          child: Container(width: 5, height: 5, decoration: BoxDecoration(color: p.purple, shape: BoxShape.circle)),
                        ),
                        Expanded(child: Text(line, style: context.type.primary.copyWith(fontWeight: FontWeight.w400, height: 1.35, fontSize: 13))),
                      ],
                    ),
                  ),
                Text(
                  n < minSample
                      ? 'Sample abhi chhota hai ($n / $minSample). Isse jaldi mat dekho.'
                      : 'Ye sirf aapke closed trades ka hisaab hai, koi prediction nahi.',
                  style: context.type.metadata.copyWith(fontSize: 10.5),
                ),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.cardGap),

          ],

          // ---- daily bars ----
          if (days.isNotEmpty) ...[
            OwlFold(
              title: 'LAST DAYS',
              headline: '${days.length} days  ·  today ${fmtSigned(tPnl)} USDT',
              headlineColor: tPnl >= 0 ? p.profit : p.loss,
              children: [_dayBars(context, p, days)],
            ),
            const SizedBox(height: AppSpacing.cardGap),
          ],

          // ---- hour-of-day heatmap (IST, by trade open time) ----
          if (hours.length == 24 && !_kSimpleAi) ...[
            _Card(child: _hourHeatmap(context, p, hours)),
            const SizedBox(height: AppSpacing.cardGap),
          ],

          // ---- exit reasons ----
          if (reasons.isNotEmpty) ...[
            OwlFold(
              title: 'HOW TRADES CLOSED',
              headline: '${reasons.first['reason']}  ·  ${_i(reasons.first['n'])} trades  ·  ${fmtSigned(_d(reasons.first['pnl']))} USDT',
              children: [_reasonRows(context, p, reasons)],
            ),
            const SizedBox(height: AppSpacing.cardGap),
          ],


          // ---- facts ----
          OwlFold(
            title: 'MORE NUMBERS',
            headline: 'Best ${fmtSigned(_d(s['best']))}  ·  Worst ${fmtSigned(_d(s['worst']))} USDT',
            children: [Wrap(
              spacing: 22,
              runSpacing: 14,
              children: [
                SizedBox(width: 130, child: _Stat('BEST TRADE', fmtSigned(_d(s['best'])), color: p.profit)),
                SizedBox(width: 130, child: _Stat('WORST TRADE', fmtSigned(_d(s['worst'])), color: p.loss)),
                SizedBox(width: 130, child: _Stat('AVG JEET', '+${_d(s['avg_win']).toStringAsFixed(2)}', color: p.profit)),
                SizedBox(width: 130, child: _Stat('AVG HAAR', '-${_d(s['avg_loss']).toStringAsFixed(2)}', color: p.loss)),
                SizedBox(width: 130, child: _Stat('LAGATAR JEET', '${_i(s['max_win_streak'])}')),
                SizedBox(width: 130, child: _Stat('LAGATAR HAAR', '${_i(s['max_loss_streak'])}')),
                SizedBox(width: 130, child: _Stat('AVG HOLD', fmtDuration(_d(s['avg_duration_s'])))),
              ],
            )],
          ),
          const SizedBox(height: AppSpacing.cardGap),

          // ---- ask AI ----
          OWLPressable(
            pressedScale: 0.985,
            onTap: () => showAiChatPopup(context,
                preset: 'Mere saare closed trades ka hisaab batao: net P&L aur sabse zyada paisa kahan se ja raha hai?'),
            child: _Card(
              glow: p.purple,
              child: Row(
                children: [
                  Icon(Icons.chat_bubble_outline_rounded, size: 18, color: p.purple),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text('AI se pucho: paisa kahan ja raha hai?',
                        style: context.type.primary.copyWith(fontWeight: FontWeight.w700, fontSize: 13.5)),
                  ),
                  Icon(Icons.arrow_forward_ios_rounded, size: 13, color: p.textMuted),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _equityCard(BuildContext context, AppPalette p, List eq) {
    final gross = <double>[];
    final net = <double>[];
    for (final e in eq) {
      if (e is List && e.length >= 3) {
        gross.add(_d(e[1]));
        net.add(_d(e[2]));
      }
    }
    if (gross.length < 2) return const SizedBox.shrink();
    final netColor = net.last >= 0 ? p.profit : p.loss;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(children: [
          const _Label('PAISA KAHAN JA RAHA HAI'),
          const Spacer(),
          Text('${gross.length} points', style: context.type.metadata),
        ]),
        const SizedBox(height: 10),
        SizedBox(
          height: 120,
          width: double.infinity,
          child: CustomPaint(
            painter: _EquityPainter(
              gross: net,
              net: net,
              grossColor: netColor,
              netColor: netColor,
              gapColor: Colors.transparent,
              axis: p.border,
            ),
          ),
        ),
        const SizedBox(height: 8),
        Text('Ab tak ${fmtSigned(net.last)} USDT',
            style: context.type.metadata.copyWith(fontSize: 11)),
      ],
    );
  }

  Widget _healthCard(BuildContext context, AppPalette p, Map<String, dynamic> h) {
    final score = _i(h['score']).clamp(0, 100);
    final reliable = h['reliable'] == true;
    final label = '${h['label'] ?? ''}';
    final col = !reliable ? p.textMuted : (score >= 65 ? p.profit : (score >= 45 ? p.warning : p.loss));
    final parts = (h['parts'] is List) ? h['parts'] as List : const [];
    return Opacity(
      opacity: reliable ? 1.0 : 0.6,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _Label('STRATEGY HEALTH'),
          const SizedBox(height: 10),
          Row(
            children: [
              SizedBox(
                width: 62,
                height: 62,
                child: Stack(
                  alignment: Alignment.center,
                  children: [
                    SizedBox(
                      width: 62,
                      height: 62,
                      child: CircularProgressIndicator(
                        value: score / 100.0,
                        strokeWidth: 6,
                        backgroundColor: p.surfaceHigher,
                        valueColor: AlwaysStoppedAnimation<Color>(col),
                      ),
                    ),
                    Text('$score', style: AppTypography.primaryData.copyWith(color: col, fontWeight: FontWeight.w800, fontSize: 20)),
                  ],
                ),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(label, style: TextStyle(color: col, fontSize: 15, fontWeight: FontWeight.w800, letterSpacing: 0.4)),
                    const SizedBox(height: 3),
                    Text(
                      reliable
                          ? '100 mein se. Sirf aapke closed trades ka hisaab, prediction nahi.'
                          : 'Sirf ${_i(h['n'])} trades hain (${_i(h['min_sample'])} chahiye). Abhi is score ko mat maano.',
                      style: context.type.metadata.copyWith(fontSize: 11),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          for (final part in parts)
            if (part is Map)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(
                  children: [
                    Expanded(flex: 5, child: Text('${part['name']}', style: context.type.metadata.copyWith(fontSize: 11), maxLines: 1, overflow: TextOverflow.ellipsis)),
                    Expanded(
                      flex: 4,
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(3),
                        child: LinearProgressIndicator(
                          value: _i(part['max']) == 0 ? 0 : (_i(part['got']) / _i(part['max'])).clamp(0.0, 1.0).toDouble(),
                          minHeight: 5,
                          backgroundColor: p.surfaceHigher,
                          valueColor: AlwaysStoppedAnimation<Color>(col),
                        ),
                      ),
                    ),
                    SizedBox(width: 44, child: Text('${_i(part['got'])}/${_i(part['max'])}', textAlign: TextAlign.right, style: context.type.metadata.copyWith(fontSize: 10.5))),
                  ],
                ),
              ),
          const SizedBox(height: 4),
          Text(
            'Ye score sirf aapki screen ke liye hai. AI isse nahi dekhta, wo hamesha asli trades aur sample size se hi jawab deta hai.',
            style: context.type.metadata.copyWith(fontSize: 10.5),
          ),
        ],
      ),
    );
  }

  Widget _hourHeatmap(BuildContext context, AppPalette p, List hours) {
    final cells = <Map<String, dynamic>>[
      for (final h in hours) if (h is Map) Map<String, dynamic>.from(h),
    ];
    if (cells.length != 24) return const SizedBox.shrink();
    var maxAbs = 0.0;
    for (final c in cells) {
      if (_i(c['n']) > 0 && _d(c['pnl']).abs() > maxAbs) maxAbs = _d(c['pnl']).abs();
    }
    if (maxAbs == 0) maxAbs = 1;
    // best / worst hour only among hours with enough trades to mean something
    Map<String, dynamic>? best;
    Map<String, dynamic>? worst;
    for (final c in cells) {
      if (_i(c['n']) < 5) continue;
      if (best == null || _d(c['pnl']) > _d(best['pnl'])) best = c;
      if (worst == null || _d(c['pnl']) < _d(worst['pnl'])) worst = c;
    }
    String hh(Map<String, dynamic> c) => '${_i(c['h']).toString().padLeft(2, '0')}h';
    Widget cell(Map<String, dynamic> c) {
      final n = _i(c['n']);
      final pnl = _d(c['pnl']);
      final empty = n == 0;
      final base = pnl >= 0 ? p.profit : p.loss;
      final strength = empty ? 0.0 : (0.18 + 0.62 * (pnl.abs() / maxAbs)).clamp(0.0, 0.8).toDouble();
      final thin = n > 0 && n < 3; // very few trades = faded
      return Expanded(
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: empty || onHour == null ? null : () => onHour!(_i(c['h'])),
          child: Opacity(
            opacity: thin ? 0.5 : 1.0,
            child: Container(
              margin: const EdgeInsets.all(2),
              height: 40,
              decoration: BoxDecoration(
                color: empty ? p.surfaceHigher.withOpacity(0.5) : base.withOpacity(strength),
                borderRadius: BorderRadius.circular(6),
              ),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(hh(c), style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w800, color: empty ? p.textMuted : p.textPrimary)),
                  Text(empty ? '-' : '$n', style: TextStyle(fontSize: 9.5, color: empty ? p.textMuted : p.textPrimary.withOpacity(0.8))),
                ],
              ),
            ),
          ),
        ),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(children: [
          const _Label('KIS GHANTE MEIN KYA HOTA HAI (IST)'),
          const Spacer(),
          Text('tap = trades', style: context.type.metadata),
        ]),
        const SizedBox(height: 8),
        for (var r = 0; r < 4; r++)
          Row(children: [for (var c = 0; c < 6; c++) cell(cells[r * 6 + c])]),
        const SizedBox(height: 8),
        if (best != null && worst != null && best['h'] != worst['h'])
          Text(
            'Sabse acha ${hh(best)} (${fmtSigned(_d(best['pnl']))} USDT, ${_i(best['n'])} trades) · '
            'sabse kharab ${hh(worst)} (${fmtSigned(_d(worst['pnl']))} USDT, ${_i(worst['n'])} trades)',
            style: context.type.metadata.copyWith(fontSize: 11),
          )
        else
          Text('Abhi har ghante mein 5+ trades nahi hain, isliye best/worst nahi bataya.',
              style: context.type.metadata.copyWith(fontSize: 11)),
        const SizedBox(height: 4),
        Text(
          'Rang = us ghante mein khule trades ka net P&L Hara = profit, laal = loss. '
          '3 se kam trades wale dibbe dhundhle hain, unpe bharosa mat karo.',
          style: context.type.metadata.copyWith(fontSize: 10.5),
        ),
      ],
    );
  }

  Widget _breakEven(BuildContext context, AppPalette p, double win, double be, double avgWin, double avgLoss) {
    final ok = win >= be;
    final col = ok ? p.profit : p.loss;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _Label('BREAK-EVEN METER'),
        const SizedBox(height: 10),
        LayoutBuilder(builder: (_, c) {
          final w = c.maxWidth;
          final wx = (w * win / 100).clamp(0.0, w).toDouble();
          final bx = (w * be / 100).clamp(0.0, w - 2).toDouble();
          return SizedBox(
            height: 30,
            child: Stack(
              children: [
                Positioned(
                  top: 11,
                  left: 0,
                  right: 0,
                  child: Container(height: 8, decoration: BoxDecoration(color: p.surfaceHigher, borderRadius: BorderRadius.circular(6))),
                ),
                Positioned(
                  top: 11,
                  left: 0,
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 600),
                    curve: Curves.easeOutCubic,
                    width: wx,
                    height: 8,
                    decoration: BoxDecoration(color: col, borderRadius: BorderRadius.circular(6)),
                  ),
                ),
                Positioned(left: bx, top: 4, child: Container(width: 2, height: 22, color: p.textPrimary)),
              ],
            ),
          );
        }),
        const SizedBox(height: 6),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text('Aapka win-rate ${win.toStringAsFixed(0)}%', style: TextStyle(color: col, fontSize: 12, fontWeight: FontWeight.w700)),
            Text('Break-even ${be.toStringAsFixed(0)}%', style: context.type.secondary.copyWith(fontSize: 12, fontWeight: FontWeight.w700)),
          ],
        ),
        const SizedBox(height: 6),
        Text(
          ok
              ? 'Win-rate break-even se upar hai. Avg jeet ${avgWin.toStringAsFixed(2)} vs avg haar ${avgLoss.toStringAsFixed(2)} USDT.'
              : 'Win-rate break-even se neeche hai. Ya jeet ka size badhao, ya haar ka size ghatao, ya kam trades lo.',
          style: context.type.metadata.copyWith(fontSize: 11),
        ),
      ],
    );
  }

  Widget _dayBars(BuildContext context, AppPalette p, List<Map<String, dynamic>> days) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(children: [
          const _Label('PICHHLE DIN, NET P&L'),
          const Spacer(),
          Text('${days.length} din', style: context.type.metadata),
        ]),
        const SizedBox(height: 10),
        SizedBox(
          height: 90,
          width: double.infinity,
          child: CustomPaint(
            painter: _DayBarsPainter(
              values: [for (final d in days) _d(d['pnl'])],
              up: p.profit,
              down: p.loss,
              axis: p.border,
            ),
          ),
        ),
        const SizedBox(height: 4),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(_ymdShort('${days.first['d']}'), style: context.type.metadata.copyWith(fontSize: 10)),
            Text(_ymdShort('${days.last['d']}'), style: context.type.metadata.copyWith(fontSize: 10)),
          ],
        ),
      ],
    );
  }

  Widget _reasonRows(BuildContext context, AppPalette p, List<Map<String, dynamic>> reasons) {
    var maxN = 1;
    for (final r in reasons) {
      if (_i(r['n']) > maxN) maxN = _i(r['n']);
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _Label('TRADE KAISE BAND HUE'),
        const SizedBox(height: 10),
        for (final r in reasons)
          Padding(
            padding: const EdgeInsets.only(bottom: 9),
            child: Row(
              children: [
                SizedBox(width: 74, child: Text('${r['reason']}', style: context.type.primary.copyWith(fontSize: 12.5, fontWeight: FontWeight.w700), maxLines: 1, overflow: TextOverflow.ellipsis)),
                Expanded(
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(4),
                    child: LinearProgressIndicator(
                      value: _i(r['n']) / maxN,
                      minHeight: 6,
                      backgroundColor: p.surfaceHigher,
                      valueColor: AlwaysStoppedAnimation<Color>(_d(r['pnl']) >= 0 ? p.profit : p.loss),
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                SizedBox(width: 30, child: Text('${_i(r['n'])}', textAlign: TextAlign.right, style: context.type.metadata)),
                SizedBox(
                  width: 64,
                  child: Text(fmtSigned(_d(r['pnl'])),
                      textAlign: TextAlign.right,
                      style: TextStyle(color: _d(r['pnl']) >= 0 ? p.profit : p.loss, fontSize: 12, fontWeight: FontWeight.w700)),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

class _DayBarsPainter extends CustomPainter {
  final List<double> values;
  final Color up;
  final Color down;
  final Color axis;
  _DayBarsPainter({required this.values, required this.up, required this.down, required this.axis});

  @override
  void paint(Canvas canvas, Size size) {
    if (values.isEmpty) return;
    var maxAbs = 0.0;
    for (final v in values) {
      if (v.abs() > maxAbs) maxAbs = v.abs();
    }
    if (maxAbs == 0) maxAbs = 1;
    final mid = size.height / 2;
    canvas.drawLine(Offset(0, mid), Offset(size.width, mid), Paint()..color = axis..strokeWidth = 1);
    final slot = size.width / values.length;
    final bw = (slot * 0.62).clamp(3.0, 22.0).toDouble();
    for (var i = 0; i < values.length; i++) {
      final h = (values[i].abs() / maxAbs) * (mid - 3);
      final x = i * slot + (slot - bw) / 2;
      final r = values[i] >= 0
          ? Rect.fromLTWH(x, mid - h, bw, _mx(h, 1.5))
          : Rect.fromLTWH(x, mid, bw, _mx(h, 1.5));
      canvas.drawRRect(RRect.fromRectAndRadius(r, const Radius.circular(2.5)), Paint()..color = values[i] >= 0 ? up : down);
    }
  }

  double _mx(double a, double b) => a > b ? a : b;

  @override
  bool shouldRepaint(covariant _DayBarsPainter old) => old.values != values || old.up != up || old.down != down;
}

class _EquityPainter extends CustomPainter {
  final List<double> gross;
  final List<double> net;
  final Color grossColor;
  final Color netColor;
  final Color gapColor;
  final Color axis;
  _EquityPainter({
    required this.gross,
    required this.net,
    required this.grossColor,
    required this.netColor,
    required this.gapColor,
    required this.axis,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final n = gross.length;
    if (n < 2 || net.length != n) return;
    var lo = 0.0;
    var hi = 0.0;
    for (var i = 0; i < n; i++) {
      if (gross[i] < lo) lo = gross[i];
      if (net[i] < lo) lo = net[i];
      if (gross[i] > hi) hi = gross[i];
      if (net[i] > hi) hi = net[i];
    }
    if (hi - lo < 1e-9) hi = lo + 1;
    const padY = 6.0;
    final h = size.height - padY * 2;
    double x(int i) => i * size.width / (n - 1);
    double y(double v) => padY + (hi - v) / (hi - lo) * h;

    canvas.drawLine(Offset(0, y(0)), Offset(size.width, y(0)), Paint()..color = axis..strokeWidth = 1);

    final gap = Path()..moveTo(x(0), y(gross[0]));
    for (var i = 1; i < n; i++) {
      gap.lineTo(x(i), y(gross[i]));
    }
    for (var i = n - 1; i >= 0; i--) {
      gap.lineTo(x(i), y(net[i]));
    }
    gap.close();
    canvas.drawPath(gap, Paint()..color = gapColor.withOpacity(0.22)..style = PaintingStyle.fill);

    Path line(List<double> v) {
      final path = Path()..moveTo(x(0), y(v[0]));
      for (var i = 1; i < n; i++) {
        path.lineTo(x(i), y(v[i]));
      }
      return path;
    }

    final stroke = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.6
      ..strokeJoin = StrokeJoin.round;
    canvas.drawPath(line(gross), stroke..color = grossColor);
    canvas.drawPath(line(net), Paint()..style = PaintingStyle.stroke..strokeWidth = 2.0..strokeJoin = StrokeJoin.round..color = netColor);
    canvas.drawCircle(Offset(x(n - 1), y(net[n - 1])), 3, Paint()..color = netColor);
  }

  @override
  bool shouldRepaint(covariant _EquityPainter old) =>
      old.gross != gross || old.net != net || old.netColor != netColor || old.grossColor != grossColor;
}

// -------------------------------------------------------------- ML shadow card --

/// OWNER-ONLY. At every trade open the backend quietly saves what the ML model
/// guessed; when the trade closes it is matched with the real result. This card shows
/// whether those guesses beat luck. These numbers are never given to the chat AI
/// (ai_guard.py blocks it) and nothing here stops or changes a trade.
class _ShadowCard extends StatefulWidget {
  const _ShadowCard();
  @override
  State<_ShadowCard> createState() => _ShadowCardState();
}

class _ShadowCardState extends State<_ShadowCard> {
  Map<String, dynamic>? _data;
  bool _loaded = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      final r = await context.read<AppProvider>().fetchAiShadow();
      if (mounted) setState(() { _data = r; _loaded = true; });
    });
  }

  Widget _target(BuildContext context, AppPalette p, String name, dynamic raw) {
    final t = (raw is Map) ? Map<String, dynamic>.from(raw) : <String, dynamic>{};
    final verdict = '${t['verdict'] ?? 'COLLECTING'}';
    final learned = verdict == 'LEARNED';
    final color = learned ? p.profit : p.textMuted;
    final n = (t['n'] is num) ? (t['n'] as num).toInt() : 0;
    String detail;
    if (t['auc'] is num) {
      detail = 'AUC ${_d(t['auc']).toStringAsFixed(2)} (luck ~${_d(t['luck_auc95']).toStringAsFixed(2)}) · '
          'top-third ${_d(t['top_rate']).toStringAsFixed(0)}% vs bottom-third ${_d(t['bottom_rate']).toStringAsFixed(0)}% · '
          'ROI ${fmtSigned(_d(t['top_roi']))}% vs ${fmtSigned(_d(t['bottom_roi']))}%';
    } else if (verdict == 'COLLECTING') {
      detail = '$n trades match hue, abhi data jama ho raha hai';
    } else {
      detail = '$n trades, ek side ke trades bahut kam hain';
    }
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(name, style: context.type.primary.copyWith(fontWeight: FontWeight.w700, fontSize: 12.5))),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
            decoration: BoxDecoration(
              color: color.withOpacity(0.14),
              borderRadius: BorderRadius.circular(6),
              border: Border.all(color: color.withOpacity(0.5), width: 0.75),
            ),
            child: Text(verdict, style: TextStyle(color: color, fontSize: 9.5, fontWeight: FontWeight.w800, letterSpacing: 0.4)),
          ),
        ]),
        const SizedBox(height: 2),
        Text(detail, style: context.type.metadata.copyWith(fontSize: 10.5)),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _data;
    if (_loaded && d == null) return const SizedBox.shrink();
    return _Card(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const _Label('ML SHADOW LOG (sirf aapke liye)'),
        const SizedBox(height: 4),
        if (d == null)
          const OwlLoading(inline: true)
        else ...[
          Text(
            '${_d(d['matched']).toInt()} trades match hue · ${_d(d['open']).toInt()} abhi khule · '
            'verdict ${_d(d['need']).toInt()}+ matched trades ke baad. Bot is se kuch nahi rokta.',
            style: context.type.metadata.copyWith(fontSize: 10.5),
          ),
          _target(context, p, 'Trade jeetega? (win)', d['win']),
          _target(context, p, 'TP1 tak jayega? (tp1)', d['tp1']),
        ],
      ]),
    );
  }
}
