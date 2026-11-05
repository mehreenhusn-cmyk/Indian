import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// R25c: ONE shared wrapper for every screen that is pushed on its own (title bar + back arrow + a Material ancestor).
/// A screen without a Scaffold has no Material above it, so every InkWell / button inside it crashed with "Material.of null" (red screen, yellow underlines).
/// Use it for any pushed screen that has no Scaffold of its own. Dual Bot has its own Scaffold and does not need it.
class OwlSubPage extends StatelessWidget {
  final String title;
  final Widget child;
  const OwlSubPage({super.key, required this.title, required this.child});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Scaffold(
      backgroundColor: p.bg,
      appBar: AppBar(
        backgroundColor: p.bg,
        elevation: 0,
        title: Text(title, style: context.type.section.copyWith(fontWeight: FontWeight.w700)),
      ),
      body: child,
    );
  }
}
