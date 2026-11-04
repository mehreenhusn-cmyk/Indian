import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import 'owl_pressable.dart';

/// R25b: the ONE plain text tab bar (same look as the Positions tabs): selected = bold + a short underline, the others grey.
/// No box, no border, no tint, no icon. Equal width, ONE row, no side scroll. Used by Dual Bot (3 tabs) and Brain Dashboard (3 sources).
/// onChanged is called only when another tab is tapped. Dart NOT compiled (the APK build is the proof).
class OwlTextTabs extends StatelessWidget {
  final List<String> names;
  final int index;
  final ValueChanged<int> onChanged;
  final double fontSize;

  const OwlTextTabs({super.key, required this.names, required this.index, required this.onChanged, this.fontSize = 15});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Row(children: [
      for (var i = 0; i < names.length; i++)
        Expanded(
          child: OWLPressable(
            pressedScale: 0.97,
            onTap: () {
              if (i != index) onChanged(i);
            },
            child: Container(
              alignment: Alignment.center,
              padding: const EdgeInsets.only(top: 8, bottom: 6),
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                FittedBox(
                  fit: BoxFit.scaleDown,
                  child: Text(names[i],
                      style: context.type.primary.copyWith(fontSize: fontSize, fontWeight: i == index ? FontWeight.w700 : FontWeight.w500, color: i == index ? p.textPrimary : p.textMuted)),
                ),
                const SizedBox(height: 5),
                Container(height: 2.5, width: 22, decoration: BoxDecoration(color: i == index ? p.textPrimary : Colors.transparent, borderRadius: BorderRadius.circular(2))),
              ]),
            ),
          ),
        ),
    ]);
  }
}
