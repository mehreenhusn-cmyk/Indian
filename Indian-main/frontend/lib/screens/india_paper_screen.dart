import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../services/india_api.dart';
import '../theme/app_theme.dart';
import '../widgets/india_drawer.dart';
import '../widgets/india_bottom_nav.dart';
import '../widgets/exit_confirm.dart';
import '../widgets/live_ticker_bar.dart' show MarketModeSwitch;
import '../services/market_mode.dart';
import '../widgets/india_ui.dart';
import '../widgets/owl_card.dart';
import 'india_chart_screen.dart';
import 'india_option_chain_screen.dart';
import 'india_pnl_report_screen.dart';
import 'india_settings_sheet.dart';
import 'india_stats_tab.dart';

/// India options PAPER terminal: Dash | Chain | Trades | Stats | Settings (bottom bar).
/// Separate from the crypto bot (own engine, own trades, own settings).
class IndiaPaperScreen extends StatefulWidget {
  const IndiaPaperScreen({super.key});

  @override
  State<IndiaPaperScreen> createState() => _IndiaPaperScreenState();
}

class _IndiaPaperScreenState extends State<IndiaPaperScreen> {
  static const _unders = ['NIFTY', 'BANKNIFTY', 'FINNIFTY'];

  late final IndiaApi _api;
  Timer? _timer;
  bool _busy = false;
  String? _error;
  Map<String, dynamic>? _st;
  List<dynamic> _positions = [];
  final Map<String, int> _tickDir = {}; // +1 up / -1 down since last poll
  int _tab = 0;

  @override
  void initState() {
    super.initState();
    _api = IndiaApi(context.read<AppProvider>().baseUrl);
    _refresh();
    _timer = Timer.periodic(const Duration(seconds: 2), (_) => _refresh());
    MarketMode.mode.addListener(_refresh); // coming back to India: refresh at once
    BackGuard.indiaGoHome = _backToDash;
  }

  /// Back button: from any page except Dash go to Dash; on Dash the root asks "Exit app?" (exit_confirm.dart).
  bool _backToDash() {
    if (!mounted || _tab == 0) return false;
    AppHaptics.light();
    setState(() => _tab = 0);
    return true;
  }

  @override
  void dispose() {
    _timer?.cancel();
    if (BackGuard.indiaGoHome == _backToDash) BackGuard.indiaGoHome = null;
    MarketMode.mode.removeListener(_refresh);
    super.dispose();
  }

  Future<void> _refresh() async {
    if (_busy || !mounted) return;
    if (MarketMode.mode.value != 'india') return; // Crypto is on screen: no polling in the background
    _busy = true;
    try {
      final st = Map<String, dynamic>.from(await _api.get('/status') as Map);
      final pos = await _api.get('/positions');
      if (!mounted) return;
      final old = (_st?['ticker'] as Map?) ?? {};
      final nu = (st['ticker'] as Map?) ?? {};
      for (final u in _unders) {
        final a = nd((old[u] as Map?)?['spot']);
        final b = nd((nu[u] as Map?)?['spot']);
        if (a != 0 && b != a) _tickDir[u] = b > a ? 1 : -1;
      }
      setState(() {
        _st = st;
        _positions = (pos['positions'] as List?) ?? [];
        _error = null;
      });
    } catch (e) {
      if (mounted) setState(() => _error = friendlyError(e));
    } finally {
      _busy = false;
    }
  }

  Future<void> _act(String path, [Map<String, dynamic>? body]) async {
    AppHaptics.light();
    try {
      await _api.post(path, body);
    } catch (e) {
      if (mounted) setState(() => _error = friendlyError(e));
    }
    await _refresh();
  }

  Future<void> _confirm(String msg, VoidCallback onYes) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        content: Text(msg),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Yes')),
        ],
      ),
    );
    if (ok == true) onYes();
  }

  // --------------------------------------------------------------- build ---
  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = context.type;
    final st = _st;
    final running = st?['running'] == true;
    final finished = st?['finished'] == true;
    final market = '${st?['market'] ?? ''}';

    // No forced text scale any more: the phone's own font-size setting is respected.
    return Scaffold(
      bottomNavigationBar: IndiaBottomNav(index: _tab, openTrades: _positions.length, onTap: (i) => setState(() => _tab = i)),
      drawer: IndiaDrawer(
        sourceLabel: '${st?['source_label'] ?? ''}',
        onCrypto: () => MarketMode.set('crypto'),
      ),
      body: SafeArea(
        child: Column(children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(AppSpacing.s, AppSpacing.s, AppSpacing.l, 0),
            child: Row(children: [
              Builder(
                builder: (ctx) => IconButton(
                  icon: const Icon(Icons.menu),
                  tooltip: 'Menu',
                  onPressed: () => Scaffold.of(ctx).openDrawer(),
                ),
              ),
              const SizedBox(width: 2),
              const MarketModeSwitch(),
              const Spacer(),
              if (market.isNotEmpty) IPill(market == 'OPEN' ? 'MARKET OPEN' : 'MARKET CLOSED', market == 'OPEN' ? p.profit : p.textSecondary),
            ]),
          ),
          if (st != null) _statusStrip(p, st, running, finished),
          if (st != null) _ticker(p, t, st),
          if (st != null && '${st['market_note'] ?? ''}'.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(AppSpacing.l, 0, AppSpacing.l, AppSpacing.s),
              child: Align(alignment: Alignment.centerLeft, child: Text('${st['market_note']}', style: IT.small(context).copyWith(color: p.warning))),
            ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.all(AppSpacing.m),
              child: Text(_error!, style: IT.small(context).copyWith(color: p.loss)),
            ),
          Expanded(child: _body(p, t)),
        ]),
      ),
    );
  }

  Widget _body(AppPalette p, AppText t) {
    final st = _st;
    if (st == null) {
      return const Center(child: CircularProgressIndicator());
    }
    final settings = Map<String, dynamic>.from((st['settings'] as Map?) ?? {});
    switch (_tab) {
      case 1:
        return IndiaChainTab(
          api: _api,
          unders: List<String>.from(((settings['underlyings'] as List?) ?? _unders).map((e) => '$e')),
          onChanged: _refresh,
        );
      case 2:
        return IndiaTradesTab(api: _api, clockIso: '${st['clock'] ?? ''}');
      case 3:
        return IndiaStatsTab(api: _api);
      case 4:
        return IndiaSettingsTab(api: _api, settings: settings, onChanged: _refresh);
      default:
        return _dashboard(p, t, st);
    }
  }

  // -------------------------------------------------------- status strip ---
  /// One line that answers "is it working?": bot state, where prices come from, how old the last price is,
  /// and how stop-losses are being checked (every live tick, or every poll).
  Widget _statusStrip(AppPalette p, Map<String, dynamic> st, bool running, bool finished) {
    final connected = st['broker_connected'] == true;
    final age = st['feed_age_ms'];
    final slMode = '${(st['sl_check'] as Map?)?['mode'] ?? 'poll'}';
    final pollSec = nd((st['sl_check'] as Map?)?['poll_sec']);
    final ageMs = age is num ? age.toInt() : null;
    final ageColor = ageMs == null ? p.textSecondary : (ageMs < 1500 ? p.profit : (ageMs < 5000 ? p.warning : p.loss));
    Widget item(String label, String value, Color c) => Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(label, maxLines: 1, style: IT.small(context).copyWith(fontSize: 9.5, letterSpacing: 0.4)),
            const SizedBox(height: 1),
            Row(children: [
              Container(width: 6, height: 6, decoration: BoxDecoration(color: c, shape: BoxShape.circle)),
              const SizedBox(width: 4),
              Expanded(child: Text(value, maxLines: 1, overflow: TextOverflow.ellipsis, style: IT.body(context).copyWith(fontSize: 12, fontWeight: FontWeight.w800, color: c))),
            ]),
          ]),
        );
    return Padding(
      padding: const EdgeInsets.fromLTRB(AppSpacing.l, 6, AppSpacing.l, AppSpacing.s),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), border: Border.all(color: p.border)),
        child: Row(children: [
          item('BOT', running ? 'RUNNING' : (finished ? 'DONE' : 'STOPPED'), running ? p.profit : p.textSecondary),
          item('DATA', connected ? 'LIVE' : 'DEMO', connected ? p.profit : p.warning),
          item('DELAY', connected ? (ageMs == null ? '—' : (ageMs < 1000 ? '$ageMs ms' : '${(ageMs / 1000).toStringAsFixed(1)} s')) : '—', connected ? ageColor : p.textSecondary),
          item('SL CHECK', slMode == 'tick' ? 'EVERY TICK' : (connected ? 'EVERY ${pollSec.toStringAsFixed(0)}s' : 'DEMO'), slMode == 'tick' ? p.profit : p.textSecondary),
        ]),
      ),
    );
  }

  // ------------------------------------------------------------- ticker ---
  Widget _ticker(AppPalette p, AppText t, Map<String, dynamic> st) {
    final tk = (st['ticker'] as Map?) ?? {};
    return Padding(
      padding: const EdgeInsets.fromLTRB(AppSpacing.l, 0, AppSpacing.l, AppSpacing.s),
      child: Row(
        children: _unders.map((u) {
          final m = Map<String, dynamic>.from((tk[u] as Map?) ?? {});
          final chg = m['chg'] == null ? null : nd(m['chg']);
          final up = (chg ?? 0) >= 0;
          final dir = _tickDir[u] ?? 0;
          final spotColor = p.textPrimary; // direction is shown by the ▲/▼ % line, not by flashing colours
          return Expanded(
            child: GestureDetector(
              onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => IndiaChartScreen(api: _api, underlying: u))),
              child: Container(
                margin: EdgeInsets.only(right: u == _unders.last ? 0 : 6),
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
                  border: Border.all(color: p.border),
                ),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    Expanded(child: Text(u, maxLines: 1, overflow: TextOverflow.ellipsis, style: IT.small(context).copyWith(fontSize: 10, fontWeight: FontWeight.w700))),
                    Icon(Icons.candlestick_chart_outlined, size: 13, color: p.accent),
                  ]),
                  const SizedBox(height: 3),
                  FittedBox(
                    fit: BoxFit.scaleDown,
                    alignment: Alignment.centerLeft,
                    child: Text(inr(nd(m['spot'])).replaceFirst('₹', ''),
                        maxLines: 1, style: IT.h(context).copyWith(color: spotColor)),
                  ),
                  const SizedBox(height: 1),
                  FittedBox(
                    fit: BoxFit.scaleDown,
                    alignment: Alignment.centerLeft,
                    child: Text(chg == null ? '—' : '${up ? '▲' : '▼'} ${num2(nd(m['chg_pct']).abs())}%',
                        maxLines: 1, style: IT.small(context).copyWith(fontWeight: FontWeight.w700, color: chg == null ? p.textSecondary : (up ? p.profit : p.loss))),
                  ),
                ]),
              ),
            ),
          );
        }).toList(),
      ),
    );
  }

  // ---------------------------------------------------------- dashboard ---
  Widget _dashboard(AppPalette p, AppText t, Map<String, dynamic> st) {
    final running = st['running'] == true;
    final finished = st['finished'] == true;
    final sm = Map<String, dynamic>.from((st['summary'] as Map?) ?? {});
    final stats = Map<String, dynamic>.from((st['stats'] as Map?) ?? {});
    final day = nd(sm['day_pnl']);
    final events = ((st['events'] as List?) ?? []);
    final pr = st['progress'];
    final prog = (pr is List && pr.length == 2 && nd(pr[1]) > 0) ? (nd(pr[0]) / nd(pr[1])).clamp(0.0, 1.0) : null;

    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView(
        padding: const EdgeInsets.all(AppSpacing.l),
        children: [
          _statusCard(p, st, prog),
          const SizedBox(height: AppSpacing.m),
          Row(children: [
            Expanded(
              child: FilledButton.icon(
                onPressed: () => _act(running ? '/stop' : '/start'),
                icon: Icon(running ? Icons.pause : Icons.play_arrow),
                label: Text(running ? 'Stop' : (finished ? 'Restart' : 'Start')),
              ),
            ),
            const SizedBox(width: AppSpacing.s),
            OutlinedButton(
              onPressed: _positions.isEmpty ? null : () => _confirm('Exit ALL open paper positions?', () => _act('/close_all')),
              child: const Text('Exit all'),
            ),
            const SizedBox(width: AppSpacing.s),
            OutlinedButton(
              onPressed: () => _confirm('Reset India paper (clears trades & cash)?', () => _act('/reset')),
              child: const Text('Reset'),
            ),
          ]),
          const SizedBox(height: AppSpacing.m),
          _capitalCard(p, Map<String, dynamic>.from((st['settings'] as Map?) ?? {})),
          const SizedBox(height: AppSpacing.s),
          ICard(
            padding: const EdgeInsets.all(12),
            child: IndiaBotSetup(
              api: _api,
              settings: Map<String, dynamic>.from((st['settings'] as Map?) ?? {}),
              onChanged: _refresh,
            ),
          ),
          const SizedBox(height: AppSpacing.m),

          // P&L card (Day / Realised / Unrealised / Charges, then account)
          ICard(
            tint: day > 0 ? p.profit.withOpacity(0.5) : (day < 0 ? p.loss.withOpacity(0.5) : null),
            padding: const EdgeInsets.all(14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text("Today's P&L", style: IT.small(context)),
              const SizedBox(height: 2),
              FittedBox(
                fit: BoxFit.scaleDown,
                alignment: Alignment.centerLeft,
                child: Text(inr(day, sign: true), style: IT.big(context).copyWith(fontSize: 26, color: pnlColor(p, day))),
              ),
              const SizedBox(height: 10),
              Row(children: [
                IMetric('Realised', inr(nd(sm['realized_today']), sign: true), color: pnlColor(p, nd(sm['realized_today']))),
                IMetric('Unrealised', inr(nd(sm['unrealized']), sign: true), color: pnlColor(p, nd(sm['unrealized']))),
                IMetric('Charges', inr(nd(sm['fees_today']))),
              ]),
              const Divider(height: 22),
              Row(children: [
                IMetric('Equity', inr(nd(sm['equity']))),
                IMetric('Cash', inr(nd(sm['cash']))),
                IMetric('Since start', inr(nd(sm['total_pnl']), sign: true), color: pnlColor(p, nd(sm['total_pnl']))),
              ]),
            ]),
          ),
          const SizedBox(height: AppSpacing.m),
          _periods(p, st),
          const SizedBox(height: AppSpacing.l),

          // Open positions
          IHeading('OPEN POSITIONS (${_positions.length})'),
          if (_positions.isEmpty) Text('No open paper positions.', style: IT.small(context)),
          ..._positions.map((e) => _positionCard(p, t, Map<String, dynamic>.from(e as Map))),
          const SizedBox(height: AppSpacing.l),

          // Signals - which trade came out and which did not
          IHeading('SIGNALS - TRADE OPENED OR SKIPPED'),
          if (events.isEmpty) Text('No signals yet. Start the engine and wait for a candle close.', style: IT.small(context)),
          ...events.take(10).map((e) {
            final m = Map<String, dynamic>.from(e as Map);
            final ok = m['ok'] == true;
            return Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Row(children: [
                Icon(ok ? Icons.check_circle : Icons.remove_circle_outline, size: 16, color: ok ? p.profit : p.warning),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    '${hm(m['time'])}  ${m['underlying']}  ${m['signal']}  →  ${ok ? 'trade opened' : 'skipped: ${m['note']}'}',
                    style: IT.small(context).copyWith(color: ok ? p.textPrimary : p.textSecondary),
                  ),
                ),
              ]),
            );
          }),
          const SizedBox(height: AppSpacing.huge),
        ],
      ),
    );
  }

  /// Top card: which bot is running (paper), where prices come from (WebSocket / REST), and any problem in one line.
  Widget _statusCard(AppPalette p, Map<String, dynamic> st, double? prog) {
    final feed = st['feed'] is Map ? Map<String, dynamic>.from(st['feed'] as Map) : null;
    final api = (feed?['api'] is Map) ? Map<String, dynamic>.from(feed!['api'] as Map) : (st['feed_api'] is Map ? Map<String, dynamic>.from(st['feed_api'] as Map) : null);
    final ws = feed?['mode'] == 'WEBSOCKET';
    final err = '${st['broker_error'] ?? ''}'.trim();
    return ICard(
      padding: const EdgeInsets.all(12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 6, runSpacing: 4, children: [
          IPill('${st['trading_mode'] ?? 'PAPER'} BOT', p.accent),
          if (feed != null) IPill(ws ? 'WEBSOCKET' : 'REST', ws ? p.profit : p.warning) else IPill('DEMO', p.warning),
          if (api != null) IPill('API ${nd(api['calls_per_min']).toInt()}/${nd(api['max_per_min']).toInt()} per min', api['limited_now'] == true ? p.loss : p.textSecondary),
        ]),
        const SizedBox(height: 6),
        Text('${st['source_label'] ?? ''}', maxLines: 2, style: IT.body(context).copyWith(color: p.warning, fontWeight: FontWeight.w600)),
        const SizedBox(height: 2),
        Text('Market time (IST): ${dayTime(st['clock'])}', style: IT.small(context)),
        if (feed != null && '${feed['note'] ?? ''}'.isNotEmpty) Text('${feed['note']}', style: IT.small(context)),
        if ('${st['trading_mode_note'] ?? ''}'.isNotEmpty) Text('${st['trading_mode_note']}', style: IT.small(context)),
        if (err.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: Text(friendlyError(err), style: IT.small(context).copyWith(color: p.warning))),
        if (prog != null) ...[
          const SizedBox(height: 6),
          LinearProgressIndicator(value: prog.toDouble(), minHeight: 3, backgroundColor: p.border),
        ],
      ]),
    );
  }

  /// Paper capital: 50,000 / 1,00,000 / 2,00,000 or your own amount. Applies after a reset.
  Widget _capitalCard(AppPalette p, Map<String, dynamic> settings) {
    final cur = nd(settings['capital']).toInt();
    const presets = [50000, 100000, 200000];
    return ICard(
      padding: const EdgeInsets.all(12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Paper capital (works even with 0 broker balance)', style: IT.small(context)),
        const SizedBox(height: 6),
        Wrap(spacing: 6, runSpacing: 6, children: [
          for (final v in presets) IChip(inr(v, dp: 0), selected: cur == v, onTap: () => _setCapital(v, cur)),
          IChip(presets.contains(cur) ? 'Custom' : 'Custom ${inr(cur, dp: 0)}', selected: !presets.contains(cur), onTap: () => _customCapital(cur)),
        ]),
      ]),
    );
  }

  void _setCapital(int v, int cur) {
    if (v == cur) return;
    _confirm('Use ${inr(v, dp: 0)} paper capital? This resets paper trades and cash.', () async {
      await _act('/settings', {'capital': v.toDouble()});
      await _act('/reset');
    });
  }

  Future<void> _customCapital(int cur) async {
    final c = TextEditingController(text: '$cur');
    final v = await showDialog<int>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Paper capital'),
        content: TextField(controller: c, keyboardType: TextInputType.number, decoration: const InputDecoration(hintText: 'Amount in rupees, min 10000')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(ctx, int.tryParse(c.text.replaceAll(',', '').trim())), child: const Text('OK')),
        ],
      ),
    );
    if (v == null || !mounted) return;
    if (v < 10000) {
      setState(() => _error = 'Capital must be at least 10,000');
      return;
    }
    _setCapital(v, cur);
  }

  /// Today / 7 days / 30 days - counted on the market's own date, not the phone's.
  Widget _periods(AppPalette p, Map<String, dynamic> st) {
    final per = Map<String, dynamic>.from((st['periods'] as Map?) ?? {});
    Widget row(String name, String key) {
      final m = Map<String, dynamic>.from((per[key] as Map?) ?? {});
      final net = nd(m['net']);
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 5),
        child: Row(children: [
          SizedBox(width: 62, child: Text(name, style: IT.body(context).copyWith(fontWeight: FontWeight.w600))),
          Expanded(child: Text('${m['trades'] ?? 0} trades · ${m['wins'] ?? 0} wins · ${nd(m['win_pct']).toStringAsFixed(0)}%', style: IT.small(context))),
          Text(inr(net, sign: true), style: IT.body(context).copyWith(fontWeight: FontWeight.w700, color: pnlColor(p, net))),
        ]),
      );
    }

    return ICard(
      padding: const EdgeInsets.fromLTRB(14, 10, 14, 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('PERFORMANCE (net of charges)', style: IT.small(context).copyWith(fontWeight: FontWeight.w700, letterSpacing: 0.8)),
        const SizedBox(height: 4),
        row('Today', 'today'),
        const Divider(height: 1),
        row('7 days', 'd7'),
        const Divider(height: 1),
        row('30 days', 'd30'),
      ]),
    );
  }

  Widget _positionCard(AppPalette p, AppText t, Map<String, dynamic> pos) {
    final c = Map<String, dynamic>.from((pos['contract'] as Map?) ?? {});
    final up = nd(pos['unrealized']);
    final tps = ((pos['tps'] as List?) ?? []).map((e) => nd(e)).toList();
    final hit = (pos['tp_hit'] as num?)?.toInt() ?? 0;
    final moved = nd(pos['sl_spot']) != nd(pos['sl_initial']);
    final side = '${pos['action']}' == 'LONG' ? 'CE' : 'PE';
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.s),
      child: ICard(
        tint: up > 0 ? p.profit.withOpacity(0.5) : (up < 0 ? p.loss.withOpacity(0.5) : null),
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
              child: Text('${pos['underlying']} ${c['strike']} $side', style: IT.body(context).copyWith(fontWeight: FontWeight.w700)),
            ),
            Text(inr(up, sign: true), style: IT.h(context).copyWith(color: pnlColor(p, up))),
          ]),
          const SizedBox(height: 4),
          Row(children: [
            Expanded(
              child: Wrap(spacing: 6, runSpacing: 4, children: [
                IPill('BUY $side', side == 'CE' ? p.profit : p.loss),
                IPill('${pos['product']}', p.accent),
                if ('${pos['tag']}'.isNotEmpty) IPill('${pos['tag']}', p.warning),
                Text('exp ${dmy(c['expiry'])}', style: IT.small(context)),
              ]),
            ),
            Text('${num2(nd(pos['unrealized_pct']))}%', style: IT.small(context).copyWith(color: pnlColor(p, up), fontWeight: FontWeight.w700)),
          ]),
          const SizedBox(height: 8),
          Row(children: [
            IMetric('Qty', '${pos['qty']}'),
            IMetric('Avg ₹', num2(nd(pos['entry_premium']))),
            IMetric('LTP ₹', num2(nd(pos['premium']))),
            IMetric('Spot', num2(nd(pos['spot']))),
          ]),
          const SizedBox(height: 8),
          Row(children: [
            IMetric('SL (spot)${moved ? ' ✓moved' : ''}', num2(nd(pos['sl_spot'])), color: p.loss),
            IMetric('Entry spot', num2(nd(pos['entry_spot']))),
            Expanded(
              child: Align(
                alignment: Alignment.centerRight,
                child: TextButton(
                  onPressed: () => _confirm('Exit this position at market?', () => _act('/close/${pos['id']}')),
                  child: const Text('Exit'),
                ),
              ),
            ),
          ]),
          const SizedBox(height: 4),
          Wrap(spacing: 6, runSpacing: 4, children: [
            for (var i = 0; i < tps.length; i++)
              IPill('TP${i + 1} ${tps[i].toStringAsFixed(0)}', p.profit, filled: hit >= i + 1),
          ]),
        ]),
      ),
    );
  }
}
