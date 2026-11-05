import 'package:flutter/material.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';

/// R31b (Part 12a): the TEXT building blocks of the new look. Used by Part 12b (Dashboard) and later screens; nothing uses them yet, so this Part changes no screen.
///   OwlSectionLabel  a small, wide-spaced, UPPERCASE heading with an optional right-hand note (like "TOP GAINERS" on the exchange page the owner liked).
///   OwlSentence      the answer in plain words: ONE headline sentence (big) and up to a few smaller lines under it. Text is passed in by the screen; nothing is invented here.
/// Dart NOT compiled.
class OwlSectionLabel extends StatelessWidget {
  final String text;
  final String note;

  const OwlSectionLabel(this.text, {super.key, this.note = ''});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: AppSpacing.sectionGap, bottom: AppSpacing.s),
      child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Expanded(child: Text(text.toUpperCase(), maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.label.copyWith(letterSpacing: 1.2, fontWeight: FontWeight.w700))),
        if (note.isNotEmpty) Flexible(child: Text(note, maxLines: 1, overflow: TextOverflow.ellipsis, textAlign: TextAlign.right, style: context.type.metadata)),
      ]),
    );
  }
}

class OwlSentence extends StatelessWidget {
  final String headline;
  final List<String> lines;

  const OwlSentence(this.headline, {super.key, this.lines = const []});

  @override
  Widget build(BuildContext context) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(headline, style: context.type.section.copyWith(fontSize: 20, fontWeight: FontWeight.w600, height: 1.25)),
      for (final l in lines) Padding(padding: const EdgeInsets.only(top: 6), child: Text(l, style: context.type.secondary.copyWith(fontSize: 15, height: 1.3))),
    ]);
  }
}
