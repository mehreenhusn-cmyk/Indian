import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// One thin bar that answers "where is my trade right now?" at a glance.
/// Left end = Stop Loss, right end = the position's target TP. The small
/// dot is the live price, the tick is the entry. Under the bar, plain words:
/// how far the stop and the target are (in %).
///
/// Stateless + cheap (no animation controllers, no blur): it only repaints
/// when its parent PositionCard rebuilds, which already happens only when
/// this position's own data changes.
class PositionGlanceBar extends StatelessWidget {
  final double? entry;
  final double? ltp;
  final double? sl;
  final double? target;
  final String targetLabel;
  final String Function(double) fmt;

  const PositionGlanceBar({
    super.key,
    required this.entry,
    required this.ltp,
    required this.sl,
    required this.target,
    required this.targetLabel,
    required this.fmt,
  });

  @override
  Widget build(BuildContext context) {
    final e = entry, l = ltp, s = sl, t = target;
    if (e == null || l == null || s == null || t == null || l == 0 || t == s) {
      return const SizedBox.shrink();
    }
    // Signed division works for LONG (sl < target) and SHORT (sl > target):
    // 0.0 = at stop, 1.0 = at target.
    double frac(double price) => ((price - s) / (t - s)).clamp(0.0, 1.0).toDouble();
    final entryFrac = frac(e);
    final ltpFrac = frac(l);
    final slAway = (l - s).abs() / l * 100;
    final tpAway = (t - l).abs() / l * 100;
    final p = context.palette;

    return Padding(
      padding: const EdgeInsets.only(top: 6, bottom: 2),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            height: 12,
            child: LayoutBuilder(
              builder: (context, c) {
                final w = c.maxWidth;
                const dot = 10.0;
                return Stack(
                  clipBehavior: Clip.none,
                  children: [
                    // red zone: stop -> entry
                    Positioned(
                      left: 0,
                      width: w * entryFrac,
                      top: 4,
                      height: 4,
                      child: DecoratedBox(
                        decoration: BoxDecoration(
                          color: p.loss.withOpacity(0.45),
                          borderRadius: const BorderRadius.horizontal(left: Radius.circular(2)),
                        ),
                      ),
                    ),
                    // green zone: entry -> target
                    Positioned(
                      left: w * entryFrac,
                      width: w * (1 - entryFrac),
                      top: 4,
                      height: 4,
                      child: DecoratedBox(
                        decoration: BoxDecoration(
                          color: p.profit.withOpacity(0.45),
                          borderRadius: const BorderRadius.horizontal(right: Radius.circular(2)),
                        ),
                      ),
                    ),
                    // entry tick
                    Positioned(
                      left: w * entryFrac - 0.5,
                      top: 1,
                      width: 1.5,
                      height: 10,
                      child: DecoratedBox(decoration: BoxDecoration(color: p.textMuted)),
                    ),
                    // live price dot
                    Positioned(
                      left: (w * ltpFrac - dot / 2).clamp(0.0, (w - dot).clamp(0.0, w)).toDouble(),
                      top: 1,
                      width: dot,
                      height: dot,
                      child: DecoratedBox(
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: ltpFrac >= entryFrac ? p.profit : p.loss,
                          border: Border.all(color: Colors.white, width: 1.2),
                        ),
                      ),
                    ),
                  ],
                );
              },
            ),
          ),
          const SizedBox(height: 3),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                'SL ${fmt(s)}  ${slAway.toStringAsFixed(2)}%',
                style: context.type.metadata.copyWith(fontSize: 10.5, color: p.loss),
              ),
              Text(
                '$targetLabel ${fmt(t)}  ${tpAway.toStringAsFixed(2)}%',
                style: context.type.metadata.copyWith(fontSize: 10.5, color: p.profit),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// Sort modes for the Positions list (session-only, no storage):
/// 0 = newest first, 1 = oldest first (the original order),
/// 2 = highest profit first, 3 = lowest profit first.
final ValueNotifier<int> positionsSortMode = ValueNotifier<int>(1);

/// Search text of the Positions tab (session-only). Matches the coin, the trade number (#id) or the signal number.
final ValueNotifier<String> positionsSearch = ValueNotifier<String>('');

/// Keeps only the positions that match [query] (empty = all). A number matches the START of the trade no or the signal no,
/// so "21" finds #21, #210 ...; text matches anywhere in the coin name.
List<dynamic> filterPositions(List<dynamic> list, String query) {
  final q = query.trim().toLowerCase().replaceAll('#', '');
  if (q.isEmpty) return list;
  return list.where((x) {
    if (x is! Map) return false;
    final sym = '${x['symbol'] ?? ''}'.toLowerCase();
    final id = '${x['id'] ?? ''}'.toLowerCase();
    final sig = x['signal_no'] == null ? '' : '${x['signal_no']}';
    return sym.contains(q) || id.startsWith(q) || (sig.isNotEmpty && sig.startsWith(q));
  }).toList();
}

List<dynamic> sortedPositions(List<dynamic> list, int mode) {
  final out = List<dynamic>.from(list);
  double pnl(dynamic x) => x is Map ? ((x['pnl_usdt'] as num?)?.toDouble() ?? 0.0) : 0.0;
  double ts(dynamic x) => x is Map ? ((x['opened_at_ts'] as num?)?.toDouble() ?? 0.0) : 0.0;
  switch (mode) {
    case 0:
      out.sort((a, b) => ts(b).compareTo(ts(a)));
      break;
    case 2:
      out.sort((a, b) => pnl(b).compareTo(pnl(a)));
      break;
    case 3:
      out.sort((a, b) => pnl(a).compareTo(pnl(b)));
      break;
    default:
      break; // 1 = backend order (oldest first)
  }
  return out;
}

/// Short bar at the top of the Positions tab: "2 winning / 1 losing" on the
/// left, and two sort chips (Time, Profit) on the right. Tap a chip to sort
/// by it; tap the active chip again to flip the direction. Counts rebuild
/// only when a count changes - not on every price tick.
/// Small search field above the position list: coin, trade no (#id) or signal no.
class PositionsSearchBar extends StatefulWidget {
  const PositionsSearchBar({super.key});

  @override
  State<PositionsSearchBar> createState() => _PositionsSearchBarState();
}

class _PositionsSearchBarState extends State<PositionsSearchBar> {
  late final TextEditingController _c = TextEditingController(text: positionsSearch.value);

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final border = OutlineInputBorder(borderRadius: BorderRadius.circular(AppSpacing.radiusPill), borderSide: BorderSide(color: p.border));
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: SizedBox(
        height: 36,
        child: TextField(
          controller: _c,
          onChanged: (v) => positionsSearch.value = v,
          textInputAction: TextInputAction.search,
          style: const TextStyle(fontSize: 13),
          decoration: InputDecoration(
            isDense: true,
            hintText: 'Search coin, trade no or signal no',
            hintStyle: TextStyle(fontSize: 12.5, color: p.textMuted),
            prefixIcon: const Icon(Icons.search_rounded, size: 18),
            suffixIcon: ValueListenableBuilder<String>(
              valueListenable: positionsSearch,
              builder: (_, v, __) => v.isEmpty
                  ? const SizedBox.shrink()
                  : IconButton(
                      icon: const Icon(Icons.close_rounded, size: 16),
                      onPressed: () {
                        _c.clear();
                        positionsSearch.value = '';
                      }),
            ),
            contentPadding: const EdgeInsets.symmetric(vertical: 0),
            border: border,
            enabledBorder: border,
          ),
        ),
      ),
    );
  }
}

class PositionsTopBar extends StatelessWidget {
  /// R22a: true = only the two sort chips (no Spacer, no bottom gap) so they can sit in the same row as the UP / DOWN pills.
  final bool inline;
  const PositionsTopBar({super.key, this.inline = false});

  @override
  Widget build(BuildContext context) {
    return Selector<AppProvider, int>(
      selector: (_, p) {
        var w = 0, l = 0;
        for (final x in p.positions) {
          if (x is! Map) continue;
          final pnl = (x['pnl_usdt'] as num?)?.toDouble() ?? 0.0;
          if (pnl >= 0) {
            w++;
          } else {
            l++;
          }
        }
        return w * 1000 + l;
      },
      builder: (context, sig, _) {
        final w = sig ~/ 1000;
        final l = sig % 1000;
        if (w + l == 0) return const SizedBox.shrink();
        final p = context.palette;
        return Padding(
          padding: EdgeInsets.only(bottom: inline ? AppSpacing.xs : AppSpacing.s),
          child: Row(
            mainAxisSize: inline ? MainAxisSize.min : MainAxisSize.max,
            children: [
              if (!inline) const Spacer(),
              ValueListenableBuilder<int>(
                valueListenable: positionsSortMode,
                builder: (context, mode, _) {
                  Widget sortChip(String label, bool active, bool down, VoidCallback onTap) {
                    final c = active ? p.accent : p.textMuted;
                    return GestureDetector(
                      behavior: HitTestBehavior.opaque,
                      onTap: onTap,
                      child: Container(
                        margin: const EdgeInsets.only(left: 6),
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: active ? p.accent.withOpacity(0.14) : Colors.transparent,
                          borderRadius: BorderRadius.circular(AppSpacing.radiusPill),
                          border: Border.all(color: active ? p.accent.withOpacity(0.5) : p.border, width: 0.8),
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(label,
                                style: context.type.metadata
                                    .copyWith(fontSize: 12, color: c, fontWeight: FontWeight.w700)),
                            if (active) ...[
                              const SizedBox(width: 2),
                              Icon(down ? Icons.arrow_downward_rounded : Icons.arrow_upward_rounded, size: 12, color: c),
                            ],
                          ],
                        ),
                      ),
                    );
                  }

                  final timeActive = mode == 0 || mode == 1;
                  final profitActive = mode == 2 || mode == 3;
                  return Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      sortChip('Time', timeActive, mode == 0,
                          () => positionsSortMode.value = timeActive ? (mode == 0 ? 1 : 0) : 0),
                      sortChip('Profit', profitActive, mode == 2,
                          () => positionsSortMode.value = profitActive ? (mode == 2 ? 3 : 2) : 2),
                    ],
                  );
                },
              ),
            ],
          ),
        );
      },
    );
  }
}
