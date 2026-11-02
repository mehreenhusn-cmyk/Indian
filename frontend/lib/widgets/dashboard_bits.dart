import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';
import 'owl_skeleton.dart';

/// Round 12: the small parts of the Dashboard that used to sit inside the 971-line dashboard_screen.dart.
/// Moved here word for word (only the names lost their underscore): warning banners, the catch-up line,
/// the BOT ON / PAUSED pill, the first-load skeleton and the breathing dot. No behaviour changed.

/// One banner look for every warning at the top of the Dashboard (errors, daily limit, daily target).
class DashBanner extends StatelessWidget {
  final IconData icon;
  final String text;
  final Color color;
  final bool bold;

  const DashBanner({required this.icon, required this.text, required this.color, this.bold = false});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.m),
      decoration: BoxDecoration(
        color: color.withOpacity(0.15),
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
        border: Border.all(color: color.withOpacity(0.4)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: color, size: 18),
          const SizedBox(width: AppSpacing.s),
          Expanded(
            child: Text(
              text,
              style: AppTypography.secondaryData.copyWith(color: color, fontSize: 12, fontWeight: bold ? FontWeight.w600 : null),
            ),
          ),
        ],
      ),
    );
  }
}

class DashRiskBanner extends StatelessWidget {
  final IconData icon;
  final String text;
  final bool isLoss;

  const DashRiskBanner({required this.icon, required this.text, required this.isLoss});

  @override
  Widget build(BuildContext context) =>
      DashBanner(icon: icon, text: text, color: isLoss ? context.palette.loss : context.palette.profit, bold: true);
}

class DashErrorBanner extends StatelessWidget {
  final IconData icon;
  final String text;

  const DashErrorBanner({required this.icon, required this.text});

  @override
  Widget build(BuildContext context) => DashBanner(icon: icon, text: text, color: context.palette.loss);
}

/// "Last catch-up" line: shows when the bot last re-checked open trades
/// after a restart / data gap / reconnect and what it found.
class CatchUpLine extends StatelessWidget {
  final Map<String, dynamic> info;
  const CatchUpLine(this.info);

  @override
  Widget build(BuildContext context) {
    final ts = (info['ts'] as num?)?.toDouble();
    if (ts == null) return const SizedBox.shrink();
    final at = DateTime.fromMillisecondsSinceEpoch((ts * 1000).round());
    final hh = at.hour.toString().padLeft(2, '0');
    final mm = at.minute.toString().padLeft(2, '0');
    final checked = (info['checked'] as num?)?.toInt() ?? 0;
    final closed = (info['closed'] as num?)?.toInt() ?? 0;
    final gap = (info['gap_s'] as num?)?.toInt() ?? 0;
    final gapText = '${fmtSpan(gap)} gap';
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Text(
        'Last catch-up $hh:$mm · $gapText · $checked open checked'
        '${closed > 0 ? ' · $closed closed while away' : ''}',
        style: AppTypography.metadata.copyWith(color: closed > 0 ? context.palette.warning : context.palette.textMuted, fontSize: 11),
      ),
    );
  }
}

/// FINAL ROUND: master ON/OFF pill for auto-trading, header row of
/// DashboardScreen. Reflects settings['trading_enabled'] (server default
/// True/ON when the key hasn't been explicitly set yet - see
/// execution_router.py's is_trading_enabled()). Tapping calls
/// `onToggle` (wired to provider.updateSettings in DashboardScreen's
/// build()) and shows a tiny inline spinner while the request is in
/// flight, so a slow/dropped connection can't look like a silent no-op or
/// let a double-tap fire two toggles in a row. Market data/LTP polling
/// and manual position closes are NOT gated by this pill - only new
/// order placement is (server-side, execution_router.py).
class MasterTradingTogglePill extends StatefulWidget {
  final bool enabled;
  final Future<bool> Function(bool next) onToggle;

  const MasterTradingTogglePill({required this.enabled, required this.onToggle});

  @override
  State<MasterTradingTogglePill> createState() => _MasterTradingTogglePillState();
}

class _MasterTradingTogglePillState extends State<MasterTradingTogglePill> {
  bool _busy = false;

  Future<void> _handleTap() async {
    if (_busy) return;
    final next = !widget.enabled;
    setState(() => _busy = true);
    bool ok = false;
    try {
      ok = await widget.onToggle(next);
    } catch (_) {
      ok = false;
    }
    if (!mounted) return;
    setState(() => _busy = false);
    if (!ok) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            next
                ? 'Could not resume the bot - check your connection and try again'
                : 'Could not pause the bot - check your connection and try again',
          ),
          backgroundColor: context.palette.loss,
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final isOn = widget.enabled;
    final color = isOn ? context.palette.profit : context.palette.warning;
    return GestureDetector(
      onTap: _handleTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: color.withOpacity(0.18),
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: color.withOpacity(0.55), width: 1),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (_busy)
              SizedBox(
                width: 12,
                height: 12,
                child: CircularProgressIndicator(strokeWidth: 2, color: color),
              )
            else
              isOn
                  ? _PulseDot(color: color)
                  : Icon(Icons.pause_circle_filled, size: 14, color: color),
            const SizedBox(width: 6),
            Text(
              isOn ? 'BOT ON' : 'BOT PAUSED',
              style: AppTypography.secondaryData.copyWith(color: color, fontSize: 12, fontWeight: FontWeight.w700),
            ),
          ],
        ),
      ),
    );
  }
}


/// Shimmer placeholder for the Dashboard's very first load.
class DashboardSkeleton extends StatelessWidget {
  const DashboardSkeleton();

  @override
  Widget build(BuildContext context) {
    return const SingleChildScrollView(
      physics: NeverScrollableScrollPhysics(),
      padding: EdgeInsets.all(AppSpacing.l),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          OWLSkeleton(width: 140, height: 26),
          SizedBox(height: AppSpacing.l),
          OWLSkeleton.card(height: 90),
          SizedBox(height: AppSpacing.l),
          OWLSkeleton(width: 90, height: 12),
          SizedBox(height: AppSpacing.s),
          OWLSkeleton(width: 200, height: 40),
          SizedBox(height: AppSpacing.xxl),
          Row(
            children: [
              Expanded(child: OWLSkeleton.card(height: 70)),
              SizedBox(width: AppSpacing.m),
              Expanded(child: OWLSkeleton.card(height: 70)),
            ],
          ),
          SizedBox(height: AppSpacing.xl),
          OWLSkeleton.card(height: 180),
          SizedBox(height: AppSpacing.xl),
          OWLSkeleton.card(height: 64),
          SizedBox(height: AppSpacing.s),
          OWLSkeleton.card(height: 64),
        ],
      ),
    );
  }
}

/// Small breathing dot for the "BOT ON" pill - a calm live-heartbeat cue.
class _PulseDot extends StatefulWidget {
  final Color color;
  const _PulseDot({required this.color});

  @override
  State<_PulseDot> createState() => _PulseDotState();
}

class _PulseDotState extends State<_PulseDot> with SingleTickerProviderStateMixin {
  late final AnimationController _c =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 1400))..repeat(reverse: true);

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 14,
      height: 14,
      child: AnimatedBuilder(
        animation: _c,
        builder: (context, _) => Center(
          child: Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(
              color: widget.color,
              shape: BoxShape.circle,
              boxShadow: [BoxShadow(color: widget.color.withOpacity(0.25 + 0.45 * _c.value), blurRadius: 3 + 6 * _c.value, spreadRadius: 0.5 + 1.5 * _c.value)],
            ),
          ),
        ),
      ),
    );
  }
}
