import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Small all-caps label that sits above a set of [SettingsGroup] cards
/// (e.g. TRADING / ALERTS & AI / APP) so the settings page reads as a few
/// clear sections instead of one long list.
class SettingsHeading extends StatelessWidget {
  final String text;
  const SettingsHeading(this.text, {super.key});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Align(
      alignment: Alignment.centerLeft,
      child: Padding(
      padding: const EdgeInsets.fromLTRB(4, AppSpacing.s, 4, AppSpacing.s),
      child: Text(
        text,
        style: AppTypography.metadata.copyWith(
          fontWeight: FontWeight.w500,
          fontSize: 13.5,
          color: p.textSecondary,
        ),
      ),
    ),
    );
  }
}

/// Collapsible settings card: rounded icon tile, title, a one-line summary
/// UNDER the title (so long titles/summaries never get squeezed or wrapped
/// into 3 lines) and a chevron that rotates when open.
///
/// Children are only built while the group is open.
class SettingsGroup extends StatefulWidget {
  final String title;
  final List<Widget> children;
  final bool initiallyExpanded;
  final String? summary;
  final IconData? icon;
  final Color? tint; // colour of the puffy icon tile (default: accent)

  const SettingsGroup({
    super.key,
    required this.title,
    required this.children,
    this.initiallyExpanded = true,
    this.summary,
    this.icon,
    this.tint,
  });

  @override
  State<SettingsGroup> createState() => _SettingsGroupState();
}

/// Title of the group that is open right now. Opening one group closes the
/// others, so the phone shows one open group at a time.
final ValueNotifier<String?> _openGroup = ValueNotifier<String?>(null);

class _SettingsGroupState extends State<SettingsGroup> {
  late bool _expanded;

  @override
  void initState() {
    super.initState();
    _expanded = widget.initiallyExpanded;
    if (_expanded) _openGroup.value = widget.title;
    _openGroup.addListener(_onOtherOpened);
  }

  void _onOtherOpened() {
    if (_expanded && _openGroup.value != widget.title && mounted) {
      setState(() => _expanded = false);
    }
  }

  @override
  void dispose() {
    _openGroup.removeListener(_onOtherOpened);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = context.type;
    final radius = BorderRadius.circular(AppSpacing.radiusLarge);

    return Container(
      margin: const EdgeInsets.only(bottom: AppSpacing.s),
      // Glass card: thin border, soft lavender shadow in the light theme.
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: radius,
        border: Border.all(color: p.border, width: 1),
        boxShadow: p.brightness == Brightness.dark
            ? null
            : [BoxShadow(color: p.accent.withOpacity(0.06), blurRadius: 18, offset: const Offset(0, 6))],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InkWell(
            onTap: () {
              setState(() => _expanded = !_expanded);
              if (_expanded) _openGroup.value = widget.title;
            },
            borderRadius: radius,
            child: Padding(
              padding: const EdgeInsets.symmetric(
                horizontal: AppSpacing.m,
                vertical: 9,
              ),
              child: Row(
                children: [
                  if (widget.icon != null) ...[
                    // Soft tinted icon tile (colour = the group's tint).
                    Container(
                      width: 36,
                      height: 36,
                      decoration: BoxDecoration(
                        color: (widget.tint ?? p.accent).withOpacity(0.15),
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: (widget.tint ?? p.accent).withOpacity(0.30), width: 1),
                      ),
                      child: Icon(widget.icon, size: 19, color: widget.tint ?? p.accent),
                    ),
                    const SizedBox(width: 10),
                  ],
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          widget.title,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: t.primary.copyWith(
                            fontWeight: FontWeight.w700,
                            fontSize: 14.5,
                            color: p.textPrimary,
                          ),
                        ),
                        if (widget.summary != null && widget.summary!.isNotEmpty) ...[
                          const SizedBox(height: 1),
                          Text(
                            widget.summary!,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: AppTypography.metadata.copyWith(
                              color: p.textMuted,
                              fontSize: 12,
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                  const SizedBox(width: AppSpacing.s),
                  AnimatedRotation(
                    turns: _expanded ? 0.25 : 0.0, // Binance-style ">" that turns down when open
                    duration: AppMotion.base,
                    child: Icon(
                      Icons.chevron_right_rounded,
                      size: 24,
                      color: p.textSecondary,
                    ),
                  ),
                ],
              ),
            ),
          ),
          AnimatedSize(
            duration: AppMotion.base,
            curve: AppMotion.standard,
            alignment: Alignment.topCenter,
            child: _expanded
                ? Padding(
                    padding: const EdgeInsets.fromLTRB(
                      AppSpacing.m,
                      0,
                      AppSpacing.m,
                      AppSpacing.m,
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Divider(color: p.border, height: 1),
                        const SizedBox(height: AppSpacing.m),
                        ...widget.children,
                      ],
                    ),
                  )
                : const SizedBox(width: double.infinity),
          ),
        ],
      ),
    );
  }
}
