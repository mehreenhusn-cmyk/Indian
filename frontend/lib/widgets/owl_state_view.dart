import 'package:flutter/material.dart';
import 'owl_empty_state.dart';

/// UI-A2: ONE widget for every "no normal content" situation, so no screen is ever a blank box.
/// loading -> small spinner + line, empty -> icon + title, error -> message + Retry,
/// offline -> 'Backend offline', stale -> 'Data delayed' (+ Retry when [onRetry] is given).
enum OwlViewKind { loading, empty, error, offline, stale }

class OwlStateView extends StatelessWidget {
  final OwlViewKind kind;
  final String? title; // e.g. 'Brain', 'open trades': used in the default texts
  final String? message; // overrides the default sentence
  final VoidCallback? onRetry;

  const OwlStateView({super.key, required this.kind, this.title, this.message, this.onRetry});

  const OwlStateView.loading({Key? key, String? title}) : this(key: key, kind: OwlViewKind.loading, title: title);

  @override
  Widget build(BuildContext context) {
    final what = title ?? 'data';
    switch (kind) {
      case OwlViewKind.loading:
        return OwlLoading(text: message ?? 'Loading $what...');
      case OwlViewKind.empty:
        return OWLEmptyState(
          icon: Icons.inbox_outlined,
          title: 'No $what',
          subtitle: message ?? 'Nothing here yet.',
        );
      case OwlViewKind.error:
        return OWLEmptyState(
          icon: Icons.error_outline_rounded,
          title: 'Could not load $what',
          subtitle: message ?? 'Something went wrong. Please try again.',
          actionLabel: onRetry == null ? null : 'Retry',
          onAction: onRetry,
        );
      case OwlViewKind.offline:
        return OWLEmptyState(
          icon: Icons.cloud_off_rounded,
          title: 'Backend offline',
          subtitle: message ?? 'Reconnecting... the screen fills in by itself when the backend is back.',
          actionLabel: onRetry == null ? null : 'Retry',
          onAction: onRetry,
        );
      case OwlViewKind.stale:
        return OWLEmptyState(
          icon: Icons.schedule_rounded,
          title: 'Data delayed',
          subtitle: message ?? 'The last update is old. Numbers may not be current.',
          actionLabel: onRetry == null ? null : 'Retry',
          onAction: onRetry,
        );
    }
  }
}
