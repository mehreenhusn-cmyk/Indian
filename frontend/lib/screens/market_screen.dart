import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../widgets/market_tile.dart';
import '../widgets/owl_empty_state.dart';
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
                  Text('Market Watch', style: t.section.copyWith(fontSize: 22, fontWeight: FontWeight.bold)),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: AppSpacing.m, vertical: AppSpacing.xs + 2),
                    decoration: BoxDecoration(
                      color: p.accent.withOpacity(0.12),
                      borderRadius: BorderRadius.circular(AppSpacing.radiusPill),
                    ),
                    child: Selector<AppProvider, int>(
                      selector: (_, pr) => pr.moversRev,
                      builder: (context, _rev, child) {
                        final c = _counts(context.read<AppProvider>());
                        return Text(
                          'LIVE  ·  ${c.$1} up  ·  ${c.$2} down',
                          style: t.metadata.copyWith(color: p.accent, fontWeight: FontWeight.bold),
                        );
                      },
                    ),
                  ),
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
            // Table header
            Container(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.l, vertical: AppSpacing.s),
              color: p.surfacePrimary,
              child: Row(
                children: [
                  Expanded(flex: 3, child: Text('SYMBOL', style: t.metadata)),
                  Expanded(flex: 3, child: Text('PRICE', textAlign: TextAlign.right, style: t.metadata)),
                  Expanded(flex: 2, child: Text('24H CHG', textAlign: TextAlign.right, style: t.metadata)),
                ],
              ),
            ),
            // List
            Expanded(
              child: OWLRefresh(
                onRefresh: () => context.read<AppProvider>().fetchStatus(),
                child: Selector<AppProvider, int>(
                selector: (_, p) => p.moversRev,
                builder: (context, _rev, child) {
                  final provider = context.read<AppProvider>();
                  final all = provider.movers
                      .whereType<Map>()
                      .map((e) => e.cast<String, dynamic>())
                      .toList();
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
                      subtitle: _filter == _MarketFilter.all
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
