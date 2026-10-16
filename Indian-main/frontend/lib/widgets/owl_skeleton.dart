import 'package:flutter/material.dart';
import 'package:shimmer/shimmer.dart';
import '../theme/app_theme.dart';

/// Shimmer placeholder shown while real data is still loading.
class OWLSkeleton extends StatelessWidget {
  final double? width;
  final double height;
  final double borderRadius;

  const OWLSkeleton({
    super.key,
    this.width,
    required this.height,
    this.borderRadius = AppSpacing.radiusSmall,
  });

  const OWLSkeleton.text({
    super.key,
    this.width = 80,
    this.height = 14,
    this.borderRadius = 4,
  });

  const OWLSkeleton.card({
    super.key,
    this.width = double.infinity,
    this.height = 110,
    this.borderRadius = AppSpacing.radiusMedium,
  });

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return RepaintBoundary(
      child: Shimmer.fromColors(
        baseColor: p.surfaceElevated,
        highlightColor: p.surfaceHigher,
        period: const Duration(milliseconds: 1400),
        child: Container(
          width: width,
          height: height,
          decoration: BoxDecoration(
            color: p.surfaceElevated,
            borderRadius: BorderRadius.circular(borderRadius),
            border: Border.all(color: p.border.withOpacity(0.4), width: 0.8),
          ),
        ),
      ),
    );
  }
}
