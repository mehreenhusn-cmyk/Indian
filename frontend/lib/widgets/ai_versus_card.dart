import 'dart:async';
import 'dart:math' as math;
import 'package:flutter/material.dart';
import '../utils/format.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_motion.dart';
import '../theme/app_theme.dart';
import 'ai_backup_card.dart';
import 'ai_coach_card.dart';
import 'ai_desk_card.dart';
import 'ai_live_card.dart';
import 'ai_own_card.dart';
import 'ai_pick_card.dart';
import 'ai_trail_trades_card.dart';
import 'ai_ready_meter.dart';
import 'trade_chart.dart';

/// BOT vs AI - the one merged screen (it replaces the old "Bot vs AI" Desk tab and the "Coach" tab).
///
/// Both take the SAME signal and the SAME entry (EMA50 cross). The bot follows its fixed rules. The AI manages its own
/// virtual copy of the trade and may exit earlier or later. Every trade is one row, with a small chart:
///   orange dot "B" = where the BOT exited        purple dot "A" = where the AI exited
///   dashed ring    = that side is still in the trade   tinted area = what the price did AFTER the AI left
///   red / green dashed lines = stop loss / take-profit levels of the signal
/// All numbers come from the backend (GET /api/ai/coach -> "pairs", ai_coach.py). This widget only draws them.
/// Nothing here opens, closes or changes a bot trade.
class AiVersusCard extends StatefulWidget {
  final TabController? tabs; // when given, the refresh only runs while this tab is the visible one
  final int tabIndex;
  /// 'all' = everything in one list (old layout), 'trades' = only the live / recent trade rows (Trades tab),
  /// 'summary' = scoreboard, ready meter, skips and studies without the long trade list (Bot vs AI tab).
  final String part;
  /// Optional result card shown first in the list (used by the Bot vs AI tab).
  final Widget? header;
  const AiVersusCard({super.key, this.tabs, this.tabIndex = 0, this.part = 'all', this.header});

  @override
  State<AiVersusCard> createState() => _AiVersusCardState();
}

/// Tap a row -> the TradingView-style trade chart (candles + EMA/SD + TSI/Z + ENTRY/SL/TP + B/A exit flags).
/// Kept under the old name so every caller (Bot vs AI rows, Trades tab) keeps working. See trade_chart.dart.
void showAiPairReplay(BuildContext context, Map<String, dynamic> pair) {
  AppHaptics.light();
  showTradeChart(context, pair);
}

const Color _kBotColor = Color(0xFFF59E0B);
const Color _kAiColor = Color(0xFF7C3AED);

class _AiVersusCardState extends State<AiVersusCard> with AutomaticKeepAliveClientMixin {
  Map<String, dynamic>? _d;
  bool _failed = false;
  bool _busy = false;
  DateTime _busySince = DateTime.now();
  bool _oldDesk = false;
  bool _studies = false;
  bool _guide = false;
  bool _refreshFailed = false; // the last refresh did not arrive: the numbers on screen are the OLD ones
  DateTime? _fetchedAt; // when the app last got an answer from the backend (different from when the backend BUILT it)
  String? _lastError; // plain-English reason of the last failed refresh
  String _flt = 'all';
  String _q = '';          // search: coin, trade no or signal no
  bool _introOpen = false; // the long explanation is folded away by default so the live trades are on the first screen
  bool _liveAll = false; // LIVE NOW shows the first 4 trades; the chevron opens the rest (no long scroll)
  final TextEditingController _qc = TextEditingController();
  Timer? _timer;
  Timer? _retry;
  int _fails = 0;

  @override
  bool get wantKeepAlive => true; // switching tabs keeps this screen: no rebuild, no reload

  @override
  void initState() {
    super.initState();
    _d = context.read<AppProvider>().peekAi('/api/ai/coach'); // last numbers at once, fresh ones arrive behind them
    _load();
    // Nothing on screen yet (first start, backend still building): ask again by itself every 4 s, no button needed.
    _retry = Timer.periodic(const Duration(seconds: 4), (_) {
      if (_d == null && mounted && (widget.tabs == null || widget.tabs!.index == widget.tabIndex)) _load();
    });
    _timer = Timer.periodic(const Duration(seconds: 60), (_) { // 60s (was 20s): the phone runs backend + app
      if (widget.tabs != null && widget.tabs!.index != widget.tabIndex) return; // not visible: no work
      _load();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _retry?.cancel();
    _qc.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    // A load that hangs can never block the next one for good (the screen used to sit on "Loading..." for ever).
    if (_busy && DateTime.now().difference(_busySince).inSeconds < 12) return;
    _busy = true;
    _busySince = DateTime.now();
    final app = context.read<AppProvider>();
    Map<String, dynamic>? r;
    String? err;
    try {
      r = await app.fetchAiCoach().timeout(const Duration(seconds: 12));
      if (r != null && r['building'] == true) {
        r = null;                                   // the backend is still building its first answer: not an error
        err = 'The backend is starting up. The numbers appear in a moment.';
      } else if (r == null) {
        err = app.aiLastError ?? 'The backend did not answer.';
      }
    } on TimeoutException {
      err = 'The app waited 12 s and the backend did not answer (the phone is busy).';
    } catch (e) {
      err = e.toString();
    }
    _busy = false;
    if (!mounted) return;
    setState(() {
      if (r != null) {
        _d = r;
        _fails = 0;
        _failed = false;
        _refreshFailed = false;
        _fetchedAt = DateTime.now();
        _lastError = null;
      } else if (_d == null) {
        _fails++;
        _failed = _fails >= 3;                      // the first tries are only 'loading'; the Retry button shows after 3 misses
        _lastError = err;
      } else {
        _refreshFailed = true;
        _lastError = err;
      }
    });
  }

  static double _n(dynamic v) => (v is num) ? v.toDouble() : 0.0;
  static int _i(dynamic v) => (v is num) ? v.toInt() : 0;
  static Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  static List<dynamic> _l(dynamic v) => v is List ? v : const [];
  static String _pct(num v) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(1)}%';

  static String _dur(num sec) {
    return fmtSpan(sec);
  }

  static String _hm(dynamic ts) {
    if (ts is! num) return '--:--:--';
    final d = DateTime.fromMillisecondsSinceEpoch((ts * 1000).round()); // phone's own time zone
    String t(int v) => v.toString().padLeft(2, '0');
    return '${t(d.hour)}:${t(d.minute)}:${t(d.second)}';
  }

  Color _col(AppPalette p, double v) => v > 0 ? p.profit : (v < 0 ? p.loss : p.textMuted);

  /// Bot close reasons come from the trade archive (SL, TP, TP1.., REVERSED, MANUAL ...).
  static String _botWhy(String r) {
    final u = r.toUpperCase();
    if (u.isEmpty) return 'closed';
    if (u == 'SL') return 'Stop loss hit';
    if (u == 'TP') return 'Take profit hit';
    if (u.startsWith('TP')) return 'Take profit ${u.substring(2)} hit';
    if (u == 'REVERSED') return 'EMA crossed back (reversal)';
    if (u == 'MANUAL') return 'Closed by hand';
    if (u == 'SCALP_TARGET') return 'Scalp target hit';
    if (u.contains('STALE')) return 'Closed: price feed was stale';
    return r;
  }

  /// AI close reasons are written by the backend in Hinglish; turn the known ones into plain English.
  static String _aiWhy(String r, String mode) {
    if (r.isEmpty) return '';
    if (r.contains('TRAIL')) return 'Trailing stop after TP4 (profit locked)';
    if (r.contains('SL entry par') || r.contains('SL at entry')) return 'Stop was moved to entry, trade closed at break-even';
    if (r.contains('REVERSED')) return 'EMA crossed back (reversal)';
    if (r.contains('TIMEOUT')) return '24 hour limit reached';
    if (r.contains('MARGIN')) return 'Closed to free margin for a new signal';
    if (r.contains('Z aur TSI dono') || r.contains('both turned against')) return 'Z-score and TSI both turned against the trade (basic rule)';
    if (r.contains('INDICATOR EXIT')) return 'Exited: in past trades with these indicators, closing now beat holding';
    if (r.contains('ye situation') || r.startsWith('In this situation')) return 'Exited because this Z / TSI / SD situation usually fades (learned from past cases)';
    if (r.startsWith('SL')) return 'Stop loss hit';
    return r;
  }

  /// One plain sentence: what was different between the two on this signal.
  static String _verdict(Map<String, dynamic> bot, Map<String, dynamic> ai) {
    final bOpen = bot['state'] == 'open';
    final aOpen = ai['state'] == 'open';
    final bUnknown = bot['state'] == 'unknown';
    if (ai['state'] == 'none') {
      return bOpen ? 'Bot is in this trade. The AI has no copy of it (reason below).' : 'The AI has no copy of this trade, so there is nothing to compare.';
    }
    final aRoi = _n(ai['roi']);
    if (aOpen && ai['roi'] == null) return 'No live price for this coin right now, so the AI result cannot be shown yet.';
    if (aOpen && bOpen) return 'Both are still in this trade. AI ${_pct(aRoi)}, bot ${bot['roi'] == null ? 'n/a' : _pct(_n(bot['roi']))}.';
    if (aOpen) {
      return 'AI is still in the trade (now ${_pct(aRoi)}). The bot already left with ${_pct(_n(bot['roi']))}'
          '${bot['exit_sec'] == null ? '' : ' after ${_dur(_n(bot['exit_sec']))}'}.';
    }
    if (bUnknown) return 'The bot result for this signal was not found (it may be too old).';
    if (bOpen) return 'The bot is still in the trade. The AI already left with ${_pct(aRoi)} after ${_dur(_n(ai['exit_sec']))}.';
    final diff = aRoi - _n(bot['roi']);
    if (diff.abs() < 0.5) return 'Both ended about the same (AI ${_pct(aRoi)}, bot ${_pct(_n(bot['roi']))}).';
    final dt = _n(ai['exit_sec']) - _n(bot['exit_sec']);
    final when = dt.abs() < 30 ? 'at about the same time' : (dt < 0 ? '${_dur(-dt)} earlier' : '${_dur(dt)} later');
    return 'AI left $when and finished ${_pct(diff.abs())} ${diff > 0 ? 'better' : 'worse'} than the bot.';
  }

  Widget _card(AppPalette p, Widget child, {Color? edge}) => Container(
        width: double.infinity,
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: p.surfaceElevated,
          borderRadius: BorderRadius.circular(AppSpacing.radiusMedium + 2),
          border: Border.all(color: edge ?? p.border, width: edge == null ? 1 : 1.4),
        ),
        child: child,
      );

  Widget _title(AppPalette p, String t) => Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Text(t, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, letterSpacing: 0.6, color: p.textMuted)));

  Widget _legendDot(String letter, Color c, String label, {bool ring = false}) => Row(mainAxisSize: MainAxisSize.min, children: [
        Container(
          width: 16,
          height: 16,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: ring ? Colors.transparent : c,
            shape: BoxShape.circle,
            border: Border.all(color: c, width: 1.6),
          ),
          child: Text(letter, style: TextStyle(fontSize: 8.5, fontWeight: FontWeight.w900, color: ring ? c : Colors.white)),
        ),
        const SizedBox(width: 5),
        Text(label, style: const TextStyle(fontSize: 11.5)),
      ]);

  Widget _intro(AppPalette p) {
    final small = TextStyle(fontSize: 11.5, height: 1.4, color: p.textMuted);
    return _card(
      p,
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('BOT vs AI', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, letterSpacing: 0.8, color: _kAiColor)),
        const SizedBox(height: 6),
        Text('Every trade the bot holds is listed here, the same ones you see in Positions and Alerts. Next to each one is the AI copy: the AI opens the same trade at the same entry and decides by itself when to leave. The bot is never touched.',
            style: TextStyle(fontSize: 13.5, height: 1.4, color: p.textPrimary, fontWeight: FontWeight.w600)),
        const SizedBox(height: 10),
        Wrap(spacing: 14, runSpacing: 6, children: [
          _legendDot('B', _kBotColor, 'Bot exit'),
          _legendDot('A', _kAiColor, 'AI exit'),
          _legendDot('A', _kAiColor, 'AI still in trade', ring: true),
        ]),
        const SizedBox(height: 8),
        Text('Tinted area = what the price did after the AI left. Red dashed line = stop loss. Green dashed lines = take-profit levels. '
            'Nothing here touches a bot trade.',
            style: small),
      ]),
    );
  }

  /// Search by coin, trade number (the #id of the position) or signal number.
  Widget _search(AppPalette p) => Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: TextField(
          controller: _qc,
          onChanged: (v) => setState(() => _q = v.trim()),
          textInputAction: TextInputAction.search,
          style: const TextStyle(fontSize: 13.5),
          decoration: InputDecoration(
            isDense: true,
            hintText: 'Search coin, trade no or signal no (e.g. 2112)',
            prefixIcon: const Icon(Icons.search_rounded, size: 20),
            suffixIcon: _q.isEmpty
                ? null
                : IconButton(
                    icon: const Icon(Icons.close_rounded, size: 18),
                    onPressed: () {
                      _qc.clear();
                      setState(() => _q = '');
                    }),
            border: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: BorderSide(color: p.border)),
            enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: BorderSide(color: p.border)),
            contentPadding: const EdgeInsets.symmetric(vertical: 10),
          ),
        ),
      );

  /// First thing on the screen: every trade that is open right now (bot and/or AI), one short line each.
  /// Tap a line to open its replay (price chart + Z-score + TSI).
  Widget _liveNow(AppPalette p, List<dynamic> all) {
    final live = all.map(_m).where((x) => x['live'] == true).toList();
    final botN = live.where((x) => _m(x['bot'])['state'] == 'open').length;
    final aiN = live.where((x) => _m(x['ai'])['state'] == 'open').length;
    Widget cell(String name, Color c, Map<String, dynamic> s) {
      final st = s['state'];
      final roi = s['roi'];
      String t;
      Color col = p.textMuted;
      if (st == 'none') {
        t = 'no copy';
      } else if (roi == null) {
        t = st == 'open' ? 'in' : 'out';
      } else {
        t = _pct(_n(roi));
        col = _col(p, _n(roi));
      }
      final suffix = (st == 'none' || roi == null) ? '' : (st == 'open' ? '  live' : '  out');
      return Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
        Text(name, style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w700, color: st == 'none' ? p.textMuted : c)),
        const SizedBox(height: 1),
        Text('$t$suffix', maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: st == 'none' ? p.textMuted : col)),
      ]);
    }

    final shownLive = _liveAll ? live : live.take(4).toList();

    return _card(
      p,
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Text('LIVE NOW', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, letterSpacing: 0.8, color: _kAiColor)),
          const SizedBox(width: 8),
          Text('Bot in $botN  ·  AI in $aiN', style: TextStyle(fontSize: 11.5, color: p.textMuted)),
        ]),
        const SizedBox(height: 8),
        if (live.isEmpty)
          Text('No trade is open right now. The next bot signal shows up here with its AI copy.', style: TextStyle(fontSize: 12, height: 1.35, color: p.textMuted))
        else
          for (final x in shownLive)
            InkWell(
              onTap: () => _openReplay(x),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 5),
                child: Row(children: [
                  Container(width: 6, height: 6, decoration: BoxDecoration(color: x['side'] == 'BUY' ? p.profit : p.loss, shape: BoxShape.circle)),
                  const SizedBox(width: 7),
                  Expanded(
                    flex: 5,
                    child: Text('#${x['id']} ${x['sym']}', maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800)),
                  ),
                  Expanded(flex: 4, child: cell('Bot', _kBotColor, _m(x['bot']))),
                  Expanded(flex: 4, child: cell('AI', _kAiColor, _m(x['ai']))),
                  Icon(Icons.chevron_right_rounded, size: 18, color: p.textMuted),
                ]),
              ),
            ),
        if (live.length > 4)
          InkWell(
            onTap: () => setState(() => _liveAll = !_liveAll),
            child: Padding(
              padding: const EdgeInsets.only(top: 6, bottom: 2),
              child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                Text(_liveAll ? 'Show fewer' : 'Show all ${live.length}', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: _kAiColor)),
                Icon(_liveAll ? Icons.expand_less_rounded : Icons.expand_more_rounded, size: 20, color: _kAiColor),
              ]),
            ),
          ),
      ]),
      edge: _kAiColor.withOpacity(0.45),
    );
  }

  Widget _filters(AppPalette p) {
    const items = [
      ['all', 'All'],
      ['live', 'Open now'],
      ['ai_open', 'AI still in'],
      ['ai_better', 'AI better'],
      ['bot_better', 'Bot better'],
      ['none', 'No AI copy'],
    ];
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Wrap(spacing: 8, runSpacing: 6, children: [
        for (final it in items)
          GestureDetector(
            onTap: () => setState(() => _flt = it[0]),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              decoration: BoxDecoration(
                color: _flt == it[0] ? _kAiColor.withOpacity(0.16) : p.surfaceElevated,
                borderRadius: BorderRadius.circular(16),
                border: Border.all(color: _flt == it[0] ? _kAiColor : p.border),
              ),
              child: Text(it[1],
                  style: TextStyle(fontSize: 12, fontWeight: _flt == it[0] ? FontWeight.w800 : FontWeight.w500, color: _flt == it[0] ? _kAiColor : p.textMuted)),
            ),
          ),
      ]),
    );
  }

  bool _keep(Map<String, dynamic> pr) {
    final bot = _m(pr['bot']);
    final ai = _m(pr['ai']);
    if (_q.isNotEmpty) {
      final q = _q.toLowerCase().replaceAll('#', '').trim();
      final ok = '${pr['sym']}'.toLowerCase().contains(q) ||
          '${pr['id']}'.startsWith(q) ||
          (pr['signal_no'] != null && '${pr['signal_no']}'.startsWith(q));
      if (!ok) return false;
    }
    switch (_flt) {
      case 'live':
        return pr['live'] == true;
      case 'none':
        return ai['state'] == 'none';
      case 'ai_open':
        return ai['state'] == 'open';
      case 'ai_better':
      case 'bot_better':
        if (ai['state'] != 'closed' || bot['state'] != 'closed') return false;
        final diff = _n(ai['roi']) - _n(bot['roi']);
        return _flt == 'ai_better' ? diff >= 0.5 : diff <= -0.5;
    }
    return true;
  }

  Widget _side(AppPalette p, String name, Color c, Map<String, dynamic> s, String why, String extra) {
    final open = s['state'] == 'open';
    final unknown = s['state'] == 'unknown';
    final none = s['state'] == 'none';
    final roi = s['roi'];
    if (none) {
      return Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Container(width: 8, height: 8, decoration: BoxDecoration(color: c, shape: BoxShape.circle)),
            const SizedBox(width: 5),
            Text(name, style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800, color: p.textMuted)),
          ]),
          Text('No copy', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: p.textMuted)),
          if (why.isNotEmpty) Text(why, style: TextStyle(fontSize: 11, height: 1.3, color: p.textMuted)),
        ]),
      );
    }
    return Expanded(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Container(width: 8, height: 8, decoration: BoxDecoration(color: c, shape: BoxShape.circle)),
          const SizedBox(width: 5),
          Text(name, style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800, color: p.textMuted)),
          if (open) ...[
            const SizedBox(width: 6),
            Text('IN TRADE', style: TextStyle(fontSize: 9.5, fontWeight: FontWeight.w900, letterSpacing: 0.5, color: c)),
          ],
        ]),
        Text(roi == null ? (unknown ? 'n/a' : '--') : _pct(_n(roi)),
            style: TextStyle(fontSize: 19, fontWeight: FontWeight.w800, color: roi == null ? p.textMuted : _col(p, _n(roi)))),
        if (why.isNotEmpty) Text(why, style: TextStyle(fontSize: 11.5, height: 1.3, color: p.textPrimary)),
        if (extra.isNotEmpty) Text(extra, style: TextStyle(fontSize: 11, height: 1.3, color: p.textMuted)),
      ]),
    );
  }

  /// How long after the bot the AI copy appeared ("at once" under 2 s).
  static String _copyDelay(double s) => s < 2 ? 'at once' : 'after ${_dur(s)}';

  /// One label per row: which side is still running and which has finished. The backend picks it (ai_coach.py _status).
  Widget _statusBadge(AppPalette p, Map<String, dynamic> pr, Map<String, dynamic> bot, Map<String, dynamic> ai) {
    var key = (pr['status'] ?? '').toString();
    var text = (pr['status_text'] ?? '').toString();
    if (key.isEmpty) {
      // answer from an older backend: work it out from the two states
      final b = bot['state'], a = ai['state'];
      key = b == 'open' && a == 'open' ? 'both_running' : (b == 'open' ? 'bot_running' : (a == 'open' ? 'ai_running' : 'both_closed'));
      text = key == 'both_running' ? 'BOTH RUNNING' : (key == 'bot_running' ? 'BOT RUNNING' : (key == 'ai_running' ? 'BOT CLOSED - AI STILL IN' : 'BOTH CLOSED'));
    }
    final Color c = key == 'both_running'
        ? p.profit
        : (key == 'bot_running' ? _kBotColor : (key == 'ai_running' ? _kAiColor : (key == 'ai_waiting' ? p.warning : p.textMuted)));
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(color: c.withOpacity(0.14), borderRadius: BorderRadius.circular(6)),
      child: Text(text, style: TextStyle(fontSize: 9.5, fontWeight: FontWeight.w900, letterSpacing: 0.4, color: c)),
    );
  }

  /// AI Pick's one-line call on this signal: TAKE / SKIP / WATCH and why, in plain English.
  Widget _pickLine(AppPalette p, Map<String, dynamic> pk) {
    final call = (pk['call'] ?? '').toString();
    final c = call == 'TAKE' ? p.profit : (call == 'SKIP' ? p.loss : p.warning);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(color: c.withOpacity(0.10), borderRadius: BorderRadius.circular(8), border: Border.all(color: c.withOpacity(0.35), width: 0.6)),
      child: Text('AI Pick: ${(pk['why'] ?? call).toString()}', style: TextStyle(fontSize: 11.5, height: 1.35, fontWeight: FontWeight.w600, color: p.textPrimary)),
    );
  }

  Widget _pairTile(AppPalette p, Map<String, dynamic> pr) {
    final bot = _m(pr['bot']);
    final ai = _m(pr['ai']);
    final aOpen = ai['state'] == 'open';
    final long = pr['side'] == 'BUY';
    final facts = _l(ai['facts']);
    final botExit = bot['exit_sec'] == null ? null : _n(bot['exit_sec']);
    final aiExit = ai['exit_sec'] == null ? null : _n(ai['exit_sec']);
    final aNone = ai['state'] == 'none';
    final aiWhy = aNone
        ? (ai['why'] ?? '').toString()
        : (aOpen ? 'Still managing the trade' : _aiWhy((ai['reason'] ?? '').toString(), (ai['mode'] ?? '').toString()));
    final aiMode = (ai['mode'] ?? '-').toString();
    final aiExtra = aOpen
        ? 'peak ${_pct(_n(ai['peak']))}${_i(ai['hit']) > 0 ? ' · TP${_i(ai['hit'])} hit' : ''}${ai['be'] == true ? ' · stop at entry' : ''}'
        : '${aiExit == null ? '' : 'left after ${_dur(aiExit)}'}${aiMode == 'LEARNED' ? ' · rule learned from data' : (aiMode == 'BASIC' ? ' · basic rule (still collecting data)' : '')}';
    final botWhy = bot['state'] == 'open' ? 'Still in the trade' : (bot['state'] == 'unknown' ? '' : _botWhy((bot['reason'] ?? '').toString()));
    final botExtra = botExit == null ? '' : 'left after ${_dur(botExit)}';
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () => _openReplay(pr),
      child: _card(
      p,
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Text('${pr['sym']}', style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w800)),
          const SizedBox(width: 8),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
            decoration: BoxDecoration(color: (long ? p.profit : p.loss).withOpacity(0.14), borderRadius: BorderRadius.circular(5)),
            child: Text(long ? 'LONG' : 'SHORT', style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w800, color: long ? p.profit : p.loss)),
          ),
          const SizedBox(width: 8),
          Text('${pr['tf'] ?? ''}', style: TextStyle(fontSize: 11.5, color: p.textMuted)),
          const Spacer(),
          _statusBadge(p, pr, bot, ai),
        ]),
        const SizedBox(height: 3),
        Text(
            'Trade #${pr['id']}${pr['signal_no'] != null ? ' · Signal #${pr['signal_no']}' : ''}   ·   Bot opened ${_hm(pr['t0'])}'
            '${ai['copy_after'] is num ? '   ·   AI copied ${_copyDelay(_n(ai['copy_after']))}' : ''}'
            '${bot['closed_ts'] != null ? '   ·   Bot closed ${_hm(bot['closed_ts'])}' : ''}'
            '${ai['closed_ts'] != null ? '   ·   AI closed ${_hm(ai['closed_ts'])}' : ''}',
            style: TextStyle(fontSize: 11.5, height: 1.35, color: p.textMuted)),
        const SizedBox(height: 8),
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _side(p, 'BOT', _kBotColor, bot, botWhy, botExtra),
          const SizedBox(width: 10),
          _side(p, 'AI', _kAiColor, ai, aiWhy, aiExtra),
        ]),
        if (pr['pick'] is Map) ...[
          const SizedBox(height: 8),
          _pickLine(p, _m(pr['pick'])),
        ],
        const SizedBox(height: 8),
        RepaintBoundary(
          child: SizedBox(
            height: 128,
            width: double.infinity,
            child: CustomPaint(
              painter: _PairChartPainter(
                path: _l(pr['path']).map((e) => [_n(_l(e)[0]), _n(_l(e)[1])]).toList(),
                levels: _m(pr['levels']),
                nowSec: _n(pr['now_sec']),
                botExit: botExit,
                botGross: bot['gross'] == null ? null : _n(bot['gross']),
                botOpen: bot['state'] == 'open',
                botLabel: bot['roi'] == null ? '' : (bot['state'] == 'open' ? 'Bot now ${_pct(_n(bot['roi']))}' : 'Bot out ${_pct(_n(bot['roi']))}'),
                aiLabel: ai['roi'] == null ? '' : (aOpen ? 'AI now ${_pct(_n(ai['roi']))}' : 'AI out ${_pct(_n(ai['roi']))}'),
                aiExit: aiExit,
                aiGross: ai['gross'] == null ? null : _n(ai['gross']),
                aiOpen: aOpen,
                profit: p.profit,
                loss: p.loss,
                muted: p.textMuted,
                line: p.textPrimary,
              ),
            ),
          ),
        ),
        const SizedBox(height: 6),
        Text(_verdict(bot, ai), style: TextStyle(fontSize: 12.5, height: 1.35, fontWeight: FontWeight.w700, color: p.textPrimary)),
        if (_l(pr['tags']).isNotEmpty) ...[
          const SizedBox(height: 6),
          Wrap(children: [
            for (final t in _l(pr['tags']))
              Container(
                margin: const EdgeInsets.only(right: 5, bottom: 4),
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: (_l(t)[0] == 'good' ? p.profit : p.loss).withOpacity(0.13),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text('${_l(t)[1]}',
                    style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: _l(t)[0] == 'good' ? p.profit : p.loss)),
              ),
          ]),
        ],
        if ((pr['what_if'] ?? '').toString().isNotEmpty) ...[
          const SizedBox(height: 2),
          Text('${pr['what_if']}', style: TextStyle(fontSize: 11.5, height: 1.35, fontStyle: FontStyle.italic, color: p.textMuted)),
        ],
        const SizedBox(height: 4),
        Text(pr['has_ind'] == true ? 'Tap to open the chart (entry, exits, TSI, Z-score)  >' : 'Tap to open the chart  >',
            style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: _kAiColor)),
        if (facts.isNotEmpty) ...[
          const SizedBox(height: 6),
          Text(aOpen ? 'What the AI sees now (Z-score, TSI, SD band, EMA50):' : 'What the AI saw when it left (Z-score, TSI, SD band, EMA50):',
              style: TextStyle(fontSize: 11, color: p.textMuted)),
          const SizedBox(height: 4),
          Wrap(children: [
            for (final f in facts)
              Container(
                margin: const EdgeInsets.only(right: 5, bottom: 5),
                padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                decoration: BoxDecoration(color: p.border.withOpacity(0.5), borderRadius: BorderRadius.circular(6)),
                child: Text('$f', style: TextStyle(fontSize: 11, color: p.textPrimary)),
              ),
          ]),
        ],
      ]),
      edge: aOpen ? _kAiColor.withOpacity(0.55) : null,
    ));
  }

  void _openReplay(Map<String, dynamic> pr) => showAiPairReplay(context, pr);

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final p = context.palette;
    final d = _d;
    if (d == null) {
      final why = _lastError ?? context.read<AppProvider>().aiLastError;
      return Center(
          child: Padding(
        padding: const EdgeInsets.all(24),
        child: _failed
            ? Column(mainAxisSize: MainAxisSize.min, children: [
                Text('Still not loaded. The app keeps trying by itself.${why == null ? '' : '\n$why'}', textAlign: TextAlign.center, style: TextStyle(color: p.textMuted, height: 1.4)),
                const SizedBox(height: 14),
                OutlinedButton(onPressed: _load, child: const Text('Retry')),
              ])
            : Column(mainAxisSize: MainAxisSize.min, children: [
                const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2)),
                const SizedBox(height: 12),
                Text('Loading the AI numbers...\nThe app asks again by itself.', textAlign: TextAlign.center, style: TextStyle(color: p.textMuted, height: 1.4)),
              ]),
      ));
    }
    final pairs = _l(d['pairs']).map(_m).where(_keep).toList();
    final all = _l(d['pairs']);
    final digest = (d['digest'] ?? '').toString();
    final ageS = d['ts'] is num ? (DateTime.now().millisecondsSinceEpoch / 1000.0 - (d['ts'] as num).toDouble()) : null;
    final tickAge = d['tick_age'] is num ? (d['tick_age'] as num).toInt() : null;
    final info = _m(d['data_info']); // sent by the backend: is its own build stuck, and why
    final backendStuck = info['stuck'] == true;
    final fetchedAgo = _fetchedAt == null ? null : DateTime.now().difference(_fetchedAt!).inSeconds;
    final stale = (ageS != null && ageS > 90) || (tickAge != null && tickAge > 90) || backendStuck;
    // Two different clocks, so it is clear which side has the problem:
    //   "built"   = when the backend made these numbers      "fetched" = when the app last received them
    final fresh = 'Built by the backend ${ageS == null ? '?' : _dur(math.max(0, ageS))} ago'
        '${fetchedAgo == null ? '' : ' | app fetched it ${_dur(fetchedAgo)} ago'}'
        '${tickAge == null ? '' : ' | AI engine last checked ${_dur(tickAge)} ago'}';
    // Where is the problem? Backend (it did not rebuild) or network/app (the answer did not arrive).
    String? problem;
    if (backendStuck) {
      problem = 'Problem is in the BACKEND: ${info['reason'] ?? 'the Bot vs AI build is stuck'}'
          '${info['fresh_build'] == true ? ' A fresh build was tried and worked.' : ''}';
    } else if (_refreshFailed) {
      problem = 'Problem is between the APP and the backend: ${_lastError ?? 'the last refresh did not arrive'}. These are the old numbers.';
    } else if (info['error'] != null) {
      problem = 'The backend failed its last build: ${info['error']}';
    } else if (stale) {
      problem = 'The numbers are old but the backend says it is fine. The AI engine may be paused (no new bot signal) or the phone is busy.';
    }
    final showTrades = widget.part != 'summary';
    final showSummary = widget.part != 'trades';
    final staleRow = () => Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(fresh, style: TextStyle(fontSize: 11.5, fontWeight: stale ? FontWeight.w800 : FontWeight.w500, color: stale ? p.loss : p.textMuted)),
                if (problem != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Text(problem, style: TextStyle(fontSize: 11.5, height: 1.3, fontWeight: FontWeight.w700, color: p.loss)),
                  ),
              ]),
            ),
            const SizedBox(width: 8),
            GestureDetector(
              onTap: _busy ? null : _load,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                decoration: BoxDecoration(color: _kAiColor.withOpacity(0.14), borderRadius: BorderRadius.circular(12)),
                child: Text(_busy ? 'Refreshing...' : 'Refresh now', style: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800, color: _kAiColor)),
              ),
            ),
          ]),
        );
    // Every block is built only when it scrolls into view (30 charts at once made the tab open slowly).
    final items = <Widget Function()>[
      if (widget.header != null) () => widget.header!,
      if (showTrades) () => _liveNow(p, _l(d['pairs'])),
      if (showSummary) () => Padding(padding: const EdgeInsets.only(bottom: 10), child: AiPickCard(tabs: widget.tabs, tabIndex: widget.tabIndex)),   // AI Pick: TAKE / SKIP / WATCH + scoreboard
      staleRow,
      if (showSummary && digest.isNotEmpty)
        () => _card(p, Text(digest, style: TextStyle(fontSize: 13, height: 1.4, fontWeight: FontWeight.w700, color: p.textPrimary)), edge: _kAiColor.withOpacity(0.45)),
      if (showSummary) () => _skipCard(p, _m(d['margin'])),
      if (showSummary) () => _feeCard(p, _m(d['margin'])),
      if (showSummary) () => AiCoachCard(embeddedData: d, part: 'top', onReload: _load),
      if (showSummary) () => _toggle(p, 'How to read the indicators (Z-score, TSI, SD band)', _guide, () => setState(() => _guide = !_guide)),
      if (showSummary && _guide) () => _guideCard(p, d),
      if (showTrades) () => _title(p, 'LIVE AND RECENT TRADES: BOT vs AI (${all.length})'),
      if (showTrades) () => _search(p),
      if (showTrades) () => _filters(p),
      if (showTrades && pairs.isEmpty)
        () => _card(
              p,
              Text(
                  all.isEmpty
                      ? 'No trades yet. When the bot takes its next signal, the AI opens its own copy and the row appears here.'
                      : 'No trade matches this filter right now.',
                  style: TextStyle(fontSize: 12.5, height: 1.4, color: p.textMuted)),
            ),
      if (showTrades) for (final pr in pairs) () => _pairTile(p, pr),
      if (showSummary) () => AiCoachCard(embeddedData: d, part: 'rest', onReload: _load),
      if (showSummary) () => _toggle(p, 'More studies (exit rules, SD levels)', _studies, () => setState(() => _studies = !_studies)),
      if (showSummary && _studies) () => const AiDeskCard(embedded: true, part: 'studies'),
      if (showSummary) () => const AiLiveCard(),
      if (showSummary) () => const AiBackupCard(),
    ];
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView.builder(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.s, AppSpacing.l, 96),
        itemCount: items.length,
        itemBuilder: (_, i) => items[i](),
      ),
    );
  }

  /// Every P&L number in this app is AFTER the exchange fee. This line says which fee, and warns when it is lower than Binance's.
  Widget _feeCard(AppPalette p, Map<String, dynamic> mg) {
    final fee = _n(mg['fee_roi']);
    final lev = _n(mg['lev']);
    final bin = _n(mg['fee_binance']);
    if (lev <= 0) return const SizedBox.shrink();
    final low = fee < bin - 0.05;
    return _card(
      p,
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, 'FEE (all P&L here is after fee)'),
        Text('Fee taken on every trade: ${fee.toStringAsFixed(2)} ROI points at ${lev.toStringAsFixed(0)}x '
            '(= ${(fee / lev).toStringAsFixed(2)}% of the position, in and out together).',
            style: TextStyle(fontSize: 12.5, height: 1.4, color: p.textPrimary, fontWeight: FontWeight.w600)),
        const SizedBox(height: 4),
        Text(
            low
                ? 'Binance taker fee (0.05% in + 0.05% out) at ${lev.toStringAsFixed(0)}x is ${bin.toStringAsFixed(2)} ROI points. Your setting is LOWER, so these numbers look better than a real account would show. The fee is the fee_roi_pct value in backend settings_store.py: set it to ${bin.toStringAsFixed(2)}.'
                : 'Matches or is above the Binance taker fee (${bin.toStringAsFixed(2)} ROI points at ${lev.toStringAsFixed(0)}x). Funding fee (every 8h) and slippage are not included.',
            style: TextStyle(fontSize: 11.5, height: 1.35, color: low ? p.loss : p.textMuted, fontWeight: low ? FontWeight.w800 : FontWeight.w500)),
      ]),
    );
  }

  /// How many signals the AI did NOT copy (margin full, day plan, Avoid coin) and what the bot made on them.
  /// Bot lost on them = the AI saved that money. Bot won on them = the AI missed that profit.
  Widget _skipCard(AppPalette p, Map<String, dynamic> mg) {
    final mSk = _i(mg['skipped']);
    final pSk = _i(mg['plan_skipped']);
    final total = mSk + pSk;
    final done = _i(mg['skipped_done']) + _i(mg['plan_skipped_done']);
    final botPnl = _n(mg['skipped_bot_pnl']) + _n(mg['plan_skipped_bot_pnl']);
    String line;
    if (total == 0) {
      line = 'The AI has not skipped any signal yet. It takes every signal the bot takes.';
    } else if (done == 0) {
      line = 'Skipped: $total (day plan / Avoid coin $pSk, margin full $mSk). The bot trades on them are still running.';
    } else {
      final saved = botPnl < 0;
      line = 'Skipped: $total (day plan / Avoid coin $pSk, margin full $mSk). $done of them finished and the bot made '
          '${botPnl >= 0 ? '+' : ''}${botPnl.toStringAsFixed(2)} USDT on them, so the AI '
          '${saved ? 'saved ${botPnl.abs().toStringAsFixed(2)} USDT by skipping' : 'missed ${botPnl.toStringAsFixed(2)} USDT of profit by skipping'}.';
    }
    return _card(
      p,
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, 'SIGNALS THE AI SKIPPED'),
        Text(line, style: TextStyle(fontSize: 12.5, height: 1.4, color: p.textPrimary, fontWeight: FontWeight.w600)),
        if (total > 0 && done > 0) ...[
          const SizedBox(height: 4),
          Text('This is the part of the Bot vs AI gap that comes from skipping, not from exits.', style: TextStyle(fontSize: 11.5, height: 1.35, color: p.textMuted)),
        ],
      ]),
    );
  }

  /// Short plain-English guide to the three indicators, plus what the AI is reading right now on its open trades.
  Widget _guideCard(AppPalette p, Map<String, dynamic> d) {
    Widget item(String name, String text) => Padding(
          padding: const EdgeInsets.only(bottom: 9),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(name, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: _kAiColor)),
            const SizedBox(height: 2),
            Text(text, style: TextStyle(fontSize: 12.5, height: 1.4, color: p.textPrimary)),
          ]),
        );
    final opens = _l(d['open']).map(_m).where((o) => _l(o['facts']).isNotEmpty).toList();
    return _card(
      p,
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        item('Z-score', 'How far the price is from its recent average, counted in standard deviations. Near 0 is normal. Above +2 or below -2 means the price is stretched, and a move back toward the average becomes more likely. A stretched price that is going WITH your trade is a warning that profit may fade.'),
        item('TSI (momentum)', 'Shows whether buying or selling pressure is rising or falling. When the TSI line is above its signal line, momentum is rising. For a long trade that is good, for a short trade it is a warning. Both lines above 0 means buyers are stronger overall.'),
        item('SD band', 'A band around the average price. A wide band means a volatile market. Price touching the outer lines (+2 / -2) is an extreme move. Price near the middle is calm.'),
        item('How the AI uses them', 'On every closed candle the AI writes down what these three said and what the price did over the next 3 candles. After enough cases (30 or more for a situation) it knows which situations usually continue and which usually fade. Until then it only uses a basic rule and says so.'),
        if (opens.isNotEmpty) ...[
          const Divider(height: 18),
          Text('WHAT THE AI READS RIGHT NOW', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800, letterSpacing: 0.6, color: p.textMuted)),
          const SizedBox(height: 6),
          for (final o in opens.take(4))
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${o['sym']}  ${o['side'] == 'BUY' ? 'LONG' : 'SHORT'}  ${_pct(_n(o['roi']))}', style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800)),
                const SizedBox(height: 3),
                Wrap(children: [
                  for (final f in _l(o['facts']))
                    Container(
                      margin: const EdgeInsets.only(right: 5, bottom: 4),
                      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                      decoration: BoxDecoration(color: p.border.withOpacity(0.5), borderRadius: BorderRadius.circular(6)),
                      child: Text('$f', style: TextStyle(fontSize: 11, color: p.textPrimary)),
                    ),
                ]),
              ]),
            ),
        ],
      ]),
    );
  }

  Widget _toggle(AppPalette p, String label, bool open, VoidCallback onTap) => GestureDetector(
        onTap: onTap,
        child: _card(
          p,
          Row(children: [
            Expanded(child: Text(label, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: p.textPrimary))),
            Icon(open ? Icons.expand_less : Icons.expand_more, color: p.textMuted),
          ]),
        ),
      );
}

/// Small chart of ONE signal: the bot trade's saved price path (ROI %, price move x leverage, before fee), with the
/// bot exit and the AI exit marked on it. Plain canvas drawing, no animation, so it costs nothing while scrolling.
/// Green tint above the entry line = trade in profit, red tint below = trade in loss.
class _PairChartPainter extends CustomPainter {
  final List<List<double>> path; // [[seconds since entry, roi], ...]
  final Map<String, dynamic> levels; // sl, tp1..tp4 as ROI %
  final double nowSec;
  final double? botExit, botGross, aiExit, aiGross;
  final bool botOpen, aiOpen;
  final String botLabel, aiLabel;
  final Color profit, loss, muted, line;

  _PairChartPainter({
    required this.path,
    required this.levels,
    required this.nowSec,
    required this.botExit,
    required this.botGross,
    required this.botOpen,
    required this.botLabel,
    required this.aiExit,
    required this.aiGross,
    required this.aiOpen,
    required this.aiLabel,
    required this.profit,
    required this.loss,
    required this.muted,
    required this.line,
  });

  static double _lv(dynamic v) => (v is num) ? v.toDouble() : double.nan;

  void _dashed(Canvas c, Offset a, Offset b, Paint paint, {double dash = 4, double gap = 3}) {
    final total = (b - a).distance;
    if (total <= 0) return;
    final dir = (b - a) / total;
    double d = 0;
    while (d < total) {
      final e = math.min(d + dash, total);
      c.drawLine(a + dir * d, a + dir * e, paint);
      d = e + gap;
    }
  }

  void _ring(Canvas c, Offset o, Color col, String letter, {required bool hollow}) {
    if (hollow) {
      c.drawCircle(o, 13, Paint()..color = col.withOpacity(0.14));
      c.drawCircle(o, 8, Paint()..color = col.withOpacity(0.10));
      final r = Rect.fromCircle(center: o, radius: 8);
      const n = 14;
      for (var i = 0; i < n; i += 2) {
        c.drawArc(r, i * 2 * math.pi / n, 2 * math.pi / n, false,
            Paint()
              ..color = col
              ..style = PaintingStyle.stroke
              ..strokeWidth = 1.8);
      }
    } else {
      c.drawCircle(o, 8.5, Paint()..color = Colors.white.withOpacity(0.9));
      c.drawCircle(o, 7.2, Paint()..color = col);
    }
    final tp = TextPainter(
      text: TextSpan(text: letter, style: TextStyle(fontSize: 8.5, fontWeight: FontWeight.w900, color: hollow ? col : Colors.white)),
      textDirection: TextDirection.ltr,
    )..layout();
    tp.paint(c, o - Offset(tp.width / 2, tp.height / 2));
  }

  /// small text with the dot's colour; right edge at [right], clamped inside the canvas
  void _text(Canvas c, String t, Offset rightTop, Color col, double maxX, {bool bold = false, double size = 9}) {
    if (t.isEmpty) return;
    final tp = TextPainter(
      text: TextSpan(text: t, style: TextStyle(fontSize: size, fontWeight: bold ? FontWeight.w800 : FontWeight.w500, color: col)),
      textDirection: TextDirection.ltr,
    )..layout();
    final x = math.max(2.0, math.min(rightTop.dx - tp.width, maxX - tp.width));
    tp.paint(c, Offset(x, rightTop.dy));
  }

  @override
  void paint(Canvas canvas, Size size) {
    if (path.length < 2) {
      final tp = TextPainter(
        text: TextSpan(text: 'No price path was saved for this trade (older trade).', style: TextStyle(fontSize: 11, color: muted)),
        textDirection: TextDirection.ltr,
      )..layout(maxWidth: size.width);
      tp.paint(canvas, Offset((size.width - tp.width) / 2, (size.height - tp.height) / 2));
      return;
    }
    const padL = 6.0, padR = 44.0, padT = 14.0, padB = 14.0;
    final w = size.width - padL - padR;
    final h = size.height - padT - padB;

    double xMax = path.last[0];
    if (botExit != null) xMax = math.max(xMax, botExit!);
    if (aiExit != null) xMax = math.max(xMax, aiExit!);
    if (aiOpen) xMax = math.max(xMax, nowSec);
    xMax = math.max(xMax, 1.0);

    double yMin = 0, yMax = 0;
    for (final s in path) {
      yMin = math.min(yMin, s[1]);
      yMax = math.max(yMax, s[1]);
    }
    for (final v in [botGross, aiGross]) {
      if (v != null) {
        yMin = math.min(yMin, v);
        yMax = math.max(yMax, v);
      }
    }
    final sl = _lv(levels['sl']);
    final tp1 = _lv(levels['tp1']);
    if (!sl.isNaN) yMin = math.min(yMin, sl);
    if (!tp1.isNaN) yMax = math.max(yMax, tp1);
    final span0 = math.max(yMax - yMin, 1.0);
    final lo = yMin - span0 * 0.08;
    final hi = yMax + span0 * 0.08;
    double X(double t) => padL + (t / xMax) * w;
    double Y(double v) => padT + (1 - (v - lo) / (hi - lo)) * h;

    // profit zone (above entry) and loss zone (below entry)
    final y0 = Y(0).clamp(padT, padT + h).toDouble();
    canvas.drawRect(Rect.fromLTRB(padL, padT, padL + w, y0), Paint()..color = profit.withOpacity(0.06));
    canvas.drawRect(Rect.fromLTRB(padL, y0, padL + w, padT + h), Paint()..color = loss.withOpacity(0.06));
    _text(canvas, 'PROFIT', Offset(padL + 40, padT + 1), profit.withOpacity(0.7), size.width, size: 8, bold: true);
    _text(canvas, 'LOSS', Offset(padL + 30, padT + h - 22), loss.withOpacity(0.7), size.width, size: 8, bold: true);

    // area after the AI left
    if (!aiOpen && aiExit != null && aiExit! < xMax * 0.995) {
      canvas.drawRect(Rect.fromLTRB(X(aiExit!), padT - 4, padL + w, padT + h + 4), Paint()..color = _kAiColor.withOpacity(0.10));
    }

    // entry line + signal levels (with their values)
    final zero = Paint()
      ..color = muted.withOpacity(0.7)
      ..strokeWidth = 1;
    _dashed(canvas, Offset(padL, Y(0)), Offset(padL + w, Y(0)), zero, dash: 2, gap: 3);
    _text(canvas, 'entry', Offset(size.width - 2, Y(0) - 5), muted, size.width);
    final drawn = <double>[Y(0)];
    void level(String k, String name, Color col) {
      final v = _lv(levels[k]);
      if (v.isNaN || v < lo || v > hi) return;
      final pt = Paint()
        ..color = col.withOpacity(0.5)
        ..strokeWidth = 1;
      _dashed(canvas, Offset(padL, Y(v)), Offset(padL + w, Y(v)), pt);
      if (drawn.any((y) => (y - Y(v)).abs() < 9)) return; // label would sit on another label
      drawn.add(Y(v));
      _text(canvas, '$name ${v >= 0 ? '+' : ''}${v.toStringAsFixed(0)}%', Offset(size.width - 2, Y(v) - 5), col, size.width);
    }

    level('sl', 'SL', loss);
    for (final k in ['tp1', 'tp2', 'tp3', 'tp4']) {
      level(k, k.toUpperCase(), profit);
    }

    // price path
    final pth = Path()..moveTo(X(path.first[0]), Y(path.first[1]));
    for (var i = 1; i < path.length; i++) {
      pth.lineTo(X(path[i][0]), Y(path[i][1]));
    }
    canvas.drawPath(
        pth,
        Paint()
          ..color = line.withOpacity(0.85)
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.7
          ..strokeJoin = StrokeJoin.round);
    canvas.drawCircle(Offset(X(path.first[0]), Y(path.first[1])), 3, Paint()..color = line);   // start of the trade

    final end = Offset(X(path.last[0]), Y(path.last[1]));

    // the AI went on after the saved path ended (the bot was already out): dashed purple line to its position
    if (aiOpen && aiGross != null) {
      _dashed(canvas, end, Offset(X(nowSec), Y(aiGross!)), Paint()..color = _kAiColor..strokeWidth = 1.6);
    } else if (!aiOpen && aiExit != null && aiGross != null && aiExit! > path.last[0] + 1) {
      _dashed(canvas, end, Offset(X(aiExit!), Y(aiGross!)), Paint()..color = _kAiColor..strokeWidth = 1.6);
    }

    // markers: bot first, AI on top. If both sit on the same spot the AI one is nudged down.
    Offset? botPt, aiPt;
    if (botOpen) {
      botPt = end;
    } else if (botExit != null && botGross != null) {
      botPt = Offset(X(botExit!), Y(botGross!));
    }
    if (aiOpen && aiGross != null) {
      aiPt = Offset(X(nowSec), Y(aiGross!));
    } else if (aiExit != null && aiGross != null) {
      aiPt = Offset(X(aiExit!), Y(aiGross!));
    }
    final close = botPt != null && aiPt != null && (botPt - aiPt).distance < 14;
    if (close) aiPt = aiPt! + const Offset(0, 13);
    if (botPt != null) {
      _ring(canvas, botPt, _kBotColor, 'B', hollow: botOpen);
      _text(canvas, botLabel, Offset(botPt.dx - 12, botPt.dy - 17), _kBotColor, padL + w + 40, bold: true);
    }
    if (aiPt != null) {
      _ring(canvas, aiPt, _kAiColor, 'A', hollow: aiOpen);
      _text(canvas, aiLabel, Offset(aiPt.dx - 12, aiPt.dy + 5), _kAiColor, padL + w + 40, bold: true);
    }
  }

  @override
  bool shouldRepaint(covariant _PairChartPainter o) =>
      o.path != path || o.nowSec != nowSec || o.botExit != botExit || o.aiExit != aiExit || o.aiGross != aiGross || o.botGross != botGross || o.aiOpen != aiOpen || o.botOpen != botOpen;
}
