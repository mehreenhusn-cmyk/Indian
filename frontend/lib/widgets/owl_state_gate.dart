import 'package:flutter/material.dart';
import '../models/view_state.dart';
import '../theme/app_theme.dart';
import 'owl_refresh.dart';
import 'owl_state_view.dart';

/// Part 28: shows [content] when the state is content, else the matching loading / empty / error / offline view.
/// The look is the existing OwlStateView (nothing new drawn). [empty] and [loading] let a screen keep its own text or
/// its own shimmer cards. Empty / error / offline are wrapped in OWLPullEmpty so pull-to-refresh still works there.
class OwlStateGate extends StatelessWidget {
  final ViewState state;
  final String what; // e.g. 'open positions': used in the default texts
  final Widget? content;
  final Widget? empty;
  final Widget? loading;
  final VoidCallback? onRetry;
  final String? errorText;
  final bool pullable;

  const OwlStateGate({
    super.key,
    required this.state,
    required this.what,
    this.content,
    this.empty,
    this.loading,
    this.onRetry,
    this.errorText,
    this.pullable = true,
  });

  Widget _pull(Widget w) => pullable ? OWLPullEmpty(child: w) : w;

  @override
  Widget build(BuildContext context) {
    switch (state) {
      case ViewState.content:
        return content ?? const SizedBox.shrink();
      case ViewState.loading:
        return loading ?? OwlStateView.loading(title: what);
      case ViewState.empty:
        return _pull(empty ?? OwlStateView(kind: OwlViewKind.empty, title: what));
      case ViewState.error:
        return _pull(OwlStateView(kind: OwlViewKind.error, title: what, message: errorText, onRetry: onRetry));
      case ViewState.offline:
        return _pull(OwlStateView(kind: OwlViewKind.offline, onRetry: onRetry));
    }
  }
}

/// Slim "data is old" line for the top of a list. Shown only when [text] is given (the caller decides with isStaleAge).
class OwlStaleStrip extends StatelessWidget {
  final String text;
  const OwlStaleStrip({super.key, required this.text});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.l, vertical: 6),
      color: p.surface,
      child: Row(children: [
        Icon(Icons.schedule_rounded, size: 14, color: p.textMuted),
        const SizedBox(width: 8),
        Flexible(child: Text(text, style: context.type.metadata.copyWith(color: p.textMuted))),
      ]),
    );
  }
}
