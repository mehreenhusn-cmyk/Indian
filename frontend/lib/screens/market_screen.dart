import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../widgets/market_tile.dart';
import '../widgets/owl_empty_state.dart';
import '../widgets/owl_state_view.dart';
import '../widgets/live_status_chip.dart';
import '../widgets/owl_skeleton.dart';
import '../widgets/candle_chart.dart';
import '../widgets/owl_refresh.dart';
import '../widgets/owl_card.dart';
import '../theme/app_theme.dart';

class MarketScreen extends StatefulWidget {
  const MarketScreen({super.key});

  @override
  State<MarketScreen> createState() => _MarketScreenState();
}

enum _MarketFilter { all, gainers, losers }

class _MarketScreenState extends State<MarketScreen> {
  _MarketFilter _filter = _MarketFilter.all;
  // Part 4 (UI-D2): coin search. Case-insensitive 'contains' on the symbol, applied on top of the All / Gainers / Losers tab.
  final TextEditingController _search = TextEditingController();
  String _query = '';

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  /// Typed text -> Binance futures symbol ("sol" -> SOLUSDT, "BTCUSDT" stays). Lets the owner open the chart
  /// of ANY coin, even one that is not on the watchlist (the backend serves candles for any symbol).
  String _symbolFromQuery(String q) {
    final s = q.toUpperCase().replaceAll(RegExp(r'[^A-Z0-9]'), '');
    if (s.isEmpty) return '';
    return s.endsWith('USDT') ? s : '${s}USDT';
  }

  void _openTyped() {
    final sym = _symbolFromQuery(_query);
    if (sym.isNotEmpty) showCandleChartSheet(context, sym);
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = context.type;

    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            // Header
            Padding(
              padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.l, AppSpacing.l, 0),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text('Market Watch', style: t.section.copyWith(fontSize: 22, fontWeight: FontWeight.w800)),
                  // UI-LIVE: honest chip (LIVE / DELAYED / OFFLINE); the up / down counts stay in the filter tabs below.
                  const LiveStatusChip(),
                ],
              ),
            ),
            const SizedBox(height: AppSpacing.s),
            // Filter bar (All / Gainers / Losers - client-side filter over the
            // real movers stream; the backend has no per-timeframe market
            // endpoint yet, so no timeframe chips are shown here).
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.l),
              child: Selector<AppProvider, int>(
                selector: (_, pr) => pr.moversRev,
                builder: (context, _rev, child) {
                  final c = _counts(context.read<AppProvider>());
                  // UI5: same segmented look as Signals / AI tabs.
                  return OwlSegmented(
                    items: [
                      ('all', 'All  ${c.$1 + c.$2}'),
                      ('gainers', 'Gainers  ${c.$1}'),
                      ('losers', 'Losers  ${c.$2}'),
                    ],
                    active: _filter.name,
                    onPick: (k) {
                      final f = _MarketFilter.values.firstWhere((e) => e.name == k);
                      if (f != _filter) AppHaptics.light();
                      setState(() => _filter = f);
                    },
                  );
                },
              ),
            ),
            // Part 4 (UI-D2): compact coin search (same pill look as the Positions search).
            Padding(
              padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.s, AppSpacing.l, AppSpacing.s),
              child: SizedBox(
                height: 38,
                child: TextField(
                  controller: _search,
                  onChanged: (v) => setState(() => _query = v.trim().toUpperCase()),
                  textInputAction: TextInputAction.search,
                  onSubmitted: (_) => _openTyped(),
                  textCapitalization: TextCapitalization.characters,
                  style: const TextStyle(fontSize: 13),
                  decoration: InputDecoration(
                    isDense: true,
                    hintText: 'Search coin (BTC, SOL...)',
                    hintStyle: TextStyle(fontSize: 12.5, color: p.textMuted),
                    prefixIcon: const Icon(Icons.search_rounded, size: 18),
                    suffixIcon: _query.isEmpty
                        ? null
                        : IconButton(
                            icon: const Icon(Icons.close_rounded, size: 16),
                            onPressed: () {
                              _search.clear();
                              setState(() => _query = '');
                            },
                          ),
                    contentPadding: EdgeInsets.zero,
                    filled: true,
                    fillColor: p.surface,
                    enabledBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(AppSpacing.radiusPill), borderSide: BorderSide(color: p.border)),
                    focusedBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(AppSpacing.radiusPill), borderSide: BorderSide(color: p.accent.withOpacity(0.5))),
                  ),
                ),
              ),
            ),
            // Any coin (even if it is not on the watchlist): open its full chart straight from the typed text.
            if (_symbolFromQuery(_query).isNotEmpty)
              Padding(
                padding: const EdgeInsets.fromLTRB(AppSpacing.l, 0, AppSpacing.l, AppSpacing.s),
                child: InkWell(
                  borderRadius: BorderRadius.circular(AppSpacing.radiusPill),
                  onTap: _openTyped,
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
                    decoration: BoxDecoration(
                      color: p.accent.withOpacity(0.10),
                      borderRadius: BorderRadius.circular(AppSpacing.radiusPill),
                      border: Border.all(color: p.accent.withOpacity(0.5)),
                    ),
                    child: Row(children: [
                      Icon(Icons.candlestick_chart_rounded, size: 18, color: p.accent),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text('Open chart: ${_symbolFromQuery(_query)}',
                            style: TextStyle(color: p.accent, fontSize: 13, fontWeight: FontWeight.w700)),
                      ),
                      Icon(Icons.chevron_right_rounded, size: 18, color: p.accent),
                    ]),
                  ),
                ),
              ),
            // Table header
            Container(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.l, vertical: AppSpacing.s),
              decoration: BoxDecoration(color: p.bg, border: Border(bottom: BorderSide(color: p.border))),
              child: Row(
                children: [
                  Expanded(flex: 3, child: Text('SYMBOL', style: t.metadata.copyWith(color: p.textMuted, fontWeight: FontWeight.w700))),
                  Expanded(flex: 3, child: Text('PRICE', textAlign: TextAlign.right, style: t.metadata.copyWith(color: p.textMuted, fontWeight: FontWeight.w700))),
                  Expanded(flex: 2, child: Text('24H CHG', textAlign: TextAlign.right, style: t.metadata.copyWith(color: p.textMuted, fontWeight: FontWeight.w700))),
                ],
              ),
            ),
            // List
            Expanded(
              child: OWLRefresh(
                onRefresh: () => context.read<AppProvider>().fetchStatus(),
                child: Selector<AppProvider, int>(
                selector: (_, p) => Object.hash(p.moversRev, p.liveState == 'offline'),
                builder: (context, _rev, child) {
                  final provider = context.read<AppProvider>();
                  final all = provider.movers
                      .whereType<Map>()
                      .map((e) => e.cast<String, dynamic>())
                      .toList();
                  if (all.isEmpty && provider.liveState == 'offline') {
                    return OWLPullEmpty(child: OwlStateView(
                      kind: OwlViewKind.offline,
                      onRetry: () => provider.fetchStatus(),
                    ));
                  }
                  if (all.isEmpty) {
                    return ListView(
                      physics: owlPullPhysics,
                      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.l, vertical: AppSpacing.m),
                      children: List.generate(
                        6,
                        (_) => const Padding(
                          padding: EdgeInsets.symmetric(vertical: 6),
                          child: OWLSkeleton(height: 44),
                        ),
                      ),
                    );
                  }
                  final filtered = all.where((item) {
                    if (_query.isNotEmpty && !'${item['symbol'] ?? ''}'.toUpperCase().contains(_query)) return false;
                    final change = (item['change_pct'] is num) ? (item['change_pct'] as num).toDouble() : 0.0;
                    switch (_filter) {
                      case _MarketFilter.gainers:
                        return change >= 0;
                      case _MarketFilter.losers:
                        return change < 0;
                      case _MarketFilter.all:
                        return true;
                    }
                  }).toList();
                  if (filtered.isEmpty) {
                    return OWLPullEmpty(child: OWLEmptyState(
                      icon: Icons.show_chart_rounded,
                      title: 'No matching symbols',
                      subtitle: _query.isNotEmpty
                          ? 'No coin on this list matches "$_query".'
                          : _filter == _MarketFilter.all
                          ? 'No market data yet - waiting for the watchlist to load.'
                          : 'No ${_filterLabel(_filter).toLowerCase()} on the current watchlist right now.',
                    ));
                  }
                  return ListView.builder(
                    physics: owlPullPhysics,
                    itemCount: filtered.length,
                    itemBuilder: (context, index) {
                      final item = filtered[index];
                      return MarketTile(
                        item: item,
                        rank: index + 1,
                        onTap: () => showCandleChartSheet(context, '${item['symbol'] ?? ''}'),
                      );
                    },
                  );
                },
              ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// (up, down) over the same movers list the table shows. Same rule as the filter: change >= 0 is up.
  (int, int) _counts(AppProvider provider) {
    int up = 0, down = 0;
    for (final x in provider.movers) {
      if (x is! Map) continue;
      final ch = x['change_pct'];
      if (ch is num && ch < 0) {
        down++;
      } else {
        up++;
      }
    }
    return (up, down);
  }

  String _filterLabel(_MarketFilter f) {
    switch (f) {
      case _MarketFilter.all:
        return 'All';
      case _MarketFilter.gainers:
        return 'Gainers';
      case _MarketFilter.losers:
        return 'Losers';
    }
  }
}
