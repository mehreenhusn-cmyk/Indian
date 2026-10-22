import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Shared chips, summary cards and table row for the Ping tab.
class PingStatusBadge extends StatelessWidget {
  final bool stale;
  final bool alive;
  final int candidates;
  final int buyAlerts;
  final int sellAlerts;

  const PingStatusBadge({
    super.key,
    required this.stale,
    required this.alive,
    required this.candidates,
    required this.buyAlerts,
    required this.sellAlerts,
  });

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final label = stale ? 'Stale' : (alive ? 'Connected' : 'Offline');
    final color = stale ? p.warning : (alive ? p.positive : p.negative);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
        border: Border.all(color: p.border),
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
            decoration: BoxDecoration(
              color: color.withOpacity(0.15),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Text(label, style: AppTypography.metadata.copyWith(color: color, fontWeight: FontWeight.w700)),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              '$candidates coins  ·  $buyAlerts buy  ·  $sellAlerts sell',
              style: AppTypography.metadata.copyWith(color: p.textSecondary),
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }
}

class PingSummaryCard extends StatelessWidget {
  final String sentence;
  final bool smallSample;

  const PingSummaryCard({super.key, required this.sentence, this.smallSample = false});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
        border: Border.all(color: p.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(sentence, style: AppTypography.secondaryData.copyWith(color: p.textPrimary)),
          if (smallSample) ...[
            const SizedBox(height: 6),
            Text(
              'Small sample, not reliable.',
              style: AppTypography.metadata.copyWith(color: p.warning, fontWeight: FontWeight.w600),
            ),
          ],
        ],
      ),
    );
  }
}

class PingAbsorbedChip extends StatelessWidget {
  const PingAbsorbedChip({super.key});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: p.warning.withOpacity(0.15),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text('Absorbed', style: AppTypography.metadata.copyWith(color: p.warning, fontSize: 9)),
    );
  }
}

class PingLiveRow extends StatelessWidget {
  final Map row;
  final VoidCallback onTap;

  const PingLiveRow({super.key, required this.row, required this.onTap});

  Color _levelColor(BuildContext context, String? color) {
    final p = context.palette;
    if (color == 'red') return p.negative;
    if (color == 'yellow') return p.warning;
    return p.textPrimary;
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final side = (row['side'] ?? '').toString();
    final isBuy = side == 'BUY';
    final sideColor = isBuy ? p.positive : p.negative;
    final level = _levelColor(context, row['color']?.toString());
    final symbol = (row['symbol'] ?? '').toString();
    final p5 = row['pings_5m'] ?? 0;
    final p15 = row['pings_15m'] ?? 0;
    final p60 = row['pings_60m'] ?? 0;
    final netPct = row['net_vol_pct'];
    final recentNet = row['recent_net'];
    final price = row['price'];
    final move = row['move_since_first_ping_pct'];
    final absorbed = row['absorbed'] == true;
    final lastTs = row['last_ping_ts'];
    String lastIst = '—';
    if (lastTs is num) {
      final dt = DateTime.fromMillisecondsSinceEpoch((lastTs * 1000).toInt(), isUtc: true)
          .add(const Duration(hours: 5, minutes: 30));
      lastIst =
          '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
    }

    return InkWell(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        decoration: BoxDecoration(
          border: Border(bottom: BorderSide(color: p.border.withOpacity(0.6))),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    symbol.replaceAll('USDT', ''),
                    style: AppTypography.primaryData.copyWith(color: level, fontWeight: FontWeight.w700),
                  ),
                ),
                Icon(isBuy ? Icons.arrow_upward : Icons.arrow_downward, size: 14, color: sideColor),
                const SizedBox(width: 2),
                Text(isBuy ? 'BUY' : 'SELL', style: AppTypography.metadata.copyWith(color: sideColor, fontWeight: FontWeight.w700)),
                if (absorbed) ...[const SizedBox(width: 6), const PingAbsorbedChip()],
              ],
            ),
            const SizedBox(height: 4),
            Text(
              'Pings $p5 / $p15 / $p60   Net% ${_fmt(netPct)}   Recent ${_fmt(recentNet)}',
              style: AppTypography.metadata.copyWith(color: p.textSecondary, fontSize: 10),
            ),
            Text(
              'Price ${_fmt(price)}   Move ${_fmt(move)}%   Last $lastIst IST',
              style: AppTypography.metadata.copyWith(color: p.textMuted, fontSize: 10),
            ),
          ],
        ),
      ),
    );
  }

  String _fmt(dynamic v) {
    if (v == null) return '—';
    if (v is num) {
      if (v.abs() >= 1000) return v.toStringAsFixed(0);
      if (v.abs() >= 1) return v.toStringAsFixed(2);
      return v.toStringAsFixed(4);
    }
    return v.toString();
  }
}

class PingSegmentBar extends StatelessWidget {
  final int index;
  final ValueChanged<int> onChanged;
  static const labels = ['Live', 'Bot', 'Score', 'Lead'];

  const PingSegmentBar({super.key, required this.index, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Row(
      children: List.generate(labels.length, (i) {
        final selected = i == index;
        return Expanded(
          child: GestureDetector(
            onTap: () => onChanged(i),
            child: Container(
              margin: const EdgeInsets.symmetric(horizontal: 2),
              padding: const EdgeInsets.symmetric(vertical: 8),
              decoration: BoxDecoration(
                color: selected ? p.accent.withOpacity(0.15) : Colors.transparent,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: selected ? p.accent : p.border),
              ),
              child: Text(
                labels[i],
                textAlign: TextAlign.center,
                style: AppTypography.metadata.copyWith(
                  color: selected ? p.accent : p.textSecondary,
                  fontWeight: selected ? FontWeight.w700 : FontWeight.w400,
                ),
              ),
            ),
          ),
        );
      }),
    );
  }
}
