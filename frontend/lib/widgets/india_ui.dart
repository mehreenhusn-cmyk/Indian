import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// Small shared widgets for the India terminal screens.

Color pnlColor(AppPalette p, double v) => v > 0 ? p.profit : (v < 0 ? p.loss : p.textSecondary);

class IPill extends StatelessWidget {
  final String text;
  final Color color;
  final bool filled;
  const IPill(this.text, this.color, {super.key, this.filled = false});

  @override
  Widget build(BuildContext context) {
    final t = context.type;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: filled ? color : color.withOpacity(0.12),
        borderRadius: BorderRadius.circular(AppSpacing.radiusPill),
      ),
      child: Text(
        text,
        style: t.metadata.copyWith(
          color: filled ? Colors.black : color,
          fontWeight: FontWeight.w700,
          fontSize: 10,
        ),
      ),
    );
  }
}

class IHeading extends StatelessWidget {
  final String text;
  final Widget? trailing;
  const IHeading(this.text, {super.key, this.trailing});

  @override
  Widget build(BuildContext context) {
    final t = context.type;
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.s),
      child: Row(children: [
        Expanded(
          child: Text(text.toUpperCase(), style: IT.small(context).copyWith(fontWeight: FontWeight.w700, letterSpacing: 0.8)),
        ),
        if (trailing != null) trailing!,
      ]),
    );
  }
}

class IMetric extends StatelessWidget {
  final String label;
  final String value;
  final Color? color;
  final CrossAxisAlignment align;
  const IMetric(this.label, this.value, {super.key, this.color, this.align = CrossAxisAlignment.start});

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Padding(
        padding: const EdgeInsets.only(right: 8),
        child: Column(crossAxisAlignment: align, children: [
          Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: IT.small(context)),
          const SizedBox(height: 2),
          FittedBox(
            fit: BoxFit.scaleDown,
            alignment: align == CrossAxisAlignment.end ? Alignment.centerRight : Alignment.centerLeft,
            child: Text(value, maxLines: 1, style: IT.body(context).copyWith(fontWeight: FontWeight.w700, color: color)),
          ),
        ]),
      ),
    );
  }
}

/// One consistent font scale for every India screen (no more big/small mix).
class IT {
  IT._();
  static TextStyle big(BuildContext c) =>
      TextStyle(fontSize: 22, fontWeight: FontWeight.w800, color: c.palette.textPrimary);
  static TextStyle h(BuildContext c) =>
      TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: c.palette.textPrimary);
  static TextStyle body(BuildContext c) =>
      TextStyle(fontSize: 13, fontWeight: FontWeight.w500, color: c.palette.textPrimary);
  static TextStyle small(BuildContext c) =>
      TextStyle(fontSize: 11, fontWeight: FontWeight.w500, color: c.palette.textSecondary);
}

/// Single chip style used everywhere: accent when selected, quiet outline otherwise.
class IChip extends StatelessWidget {
  final String label;
  final bool selected;
  final VoidCallback? onTap;
  final IconData? icon;
  const IChip(this.label, {super.key, required this.selected, this.onTap, this.icon});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final col = selected ? p.accent : p.textSecondary;
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 6),
        decoration: BoxDecoration(
          color: selected ? p.accent.withOpacity(0.14) : Colors.transparent,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: selected ? p.accent : p.border),
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          if (icon != null) ...[Icon(icon, size: 13, color: col), const SizedBox(width: 4)],
          Text(label, maxLines: 1, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: col)),
        ]),
      ),
    );
  }
}

/// A row of single-select chips.
class IChoice<T> extends StatelessWidget {
  final List<T> values;
  final T? current;
  final String Function(T) label;
  final void Function(T) onPick;
  const IChoice({super.key, required this.values, required this.current, required this.label, required this.onPick});

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: values.map((v) => IChip(label(v), selected: v == current, onTap: () => onPick(v))).toList(),
    );
  }
}

/// Collapsible settings group (like the crypto settings): title + chevron, content when open.
class ISection extends StatefulWidget {
  final String title;
  final String? summary; // shown on the right while collapsed
  final bool initiallyOpen;
  final List<Widget> children;
  const ISection({super.key, required this.title, required this.children, this.summary, this.initiallyOpen = false});

  @override
  State<ISection> createState() => _ISectionState();
}

class _ISectionState extends State<ISection> {
  late bool _open = widget.initiallyOpen;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: p.border),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: () => setState(() => _open = !_open),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            child: Row(children: [
              Expanded(child: Text(widget.title, style: IT.h(context))),
              if (!_open && widget.summary != null)
                Flexible(child: Text(widget.summary!, maxLines: 1, overflow: TextOverflow.ellipsis, style: IT.small(context))),
              const SizedBox(width: 6),
              Icon(_open ? Icons.expand_less : Icons.expand_more, size: 20, color: p.textSecondary),
            ]),
          ),
        ),
        if (_open)
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 0, 14, 12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: widget.children),
          ),
      ]),
    );
  }
}

/// Plain bordered card in the app palette (no glow / odd colours).
class ICard extends StatelessWidget {
  final Widget child;
  final EdgeInsets padding;
  final Color? tint;
  const ICard({super.key, required this.child, this.padding = const EdgeInsets.all(14), this.tint});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Container(
      width: double.infinity,
      padding: padding,
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: tint ?? p.border),
      ),
      child: child,
    );
  }
}

/// Market switch used at the top of the India screen (Crypto | India Paper).
class MarketSwitch extends StatelessWidget {
  final VoidCallback onCrypto;
  const MarketSwitch({super.key, required this.onCrypto});

  Widget _chip(BuildContext context, String label, IconData icon, bool selected, VoidCallback onTap) {
    final p = context.palette;
    final t = context.type;
    return Expanded(
      child: GestureDetector(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: AppSpacing.m - 2),
          decoration: BoxDecoration(
            color: selected ? p.accent.withOpacity(0.15) : Colors.transparent,
            borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
            border: Border.all(color: selected ? p.accent : p.border),
          ),
          child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
            Icon(icon, size: 16, color: selected ? p.accent : p.textSecondary),
            const SizedBox(width: 6),
            Text(label,
                style: t.primary.copyWith(
                    fontWeight: FontWeight.w700, color: selected ? p.accent : p.textSecondary)),
          ]),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Row(children: [
      _chip(context, 'Crypto', Icons.currency_bitcoin, false, onCrypto),
      const SizedBox(width: AppSpacing.s),
      _chip(context, 'India Paper', Icons.show_chart, true, () {}),
    ]);
  }
}

/// Tiny equity-curve painter (no chart package needed).
class SparkLine extends StatelessWidget {
  final List<double> values;
  final Color color;
  final double height;
  const SparkLine(this.values, this.color, {super.key, this.height = 90});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: height,
      width: double.infinity,
      child: CustomPaint(painter: _SparkPainter(values, color)),
    );
  }
}

class _SparkPainter extends CustomPainter {
  final List<double> v;
  final Color color;
  _SparkPainter(this.v, this.color);

  @override
  void paint(Canvas canvas, Size size) {
    if (v.length < 2) return;
    var lo = v.reduce((a, b) => a < b ? a : b);
    var hi = v.reduce((a, b) => a > b ? a : b);
    if (hi - lo < 1e-9) {
      hi += 1;
      lo -= 1;
    }
    Offset pt(int i) => Offset(
          size.width * i / (v.length - 1),
          size.height - 6 - (size.height - 12) * (v[i] - lo) / (hi - lo),
        );
    final path = Path()..moveTo(pt(0).dx, pt(0).dy);
    for (var i = 1; i < v.length; i++) {
      path.lineTo(pt(i).dx, pt(i).dy);
    }
    final fill = Path.from(path)
      ..lineTo(size.width, size.height)
      ..lineTo(0, size.height)
      ..close();
    canvas.drawPath(fill, Paint()..color = color.withOpacity(0.10));
    canvas.drawPath(
      path,
      Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2,
    );
  }

  @override
  bool shouldRepaint(covariant _SparkPainter old) => old.v != v || old.color != color;
}
