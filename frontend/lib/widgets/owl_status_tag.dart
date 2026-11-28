import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import 'owl_hero_card.dart';

/// Part 22 (29 Nov 2026): design kit, piece 3 = status tag, evidence tag, check row, screen intro.
/// These are the 4 small pieces the new screens (Parts 23 to 35) share, so a state is always written in the same colour and the same plain words.
/// Plain widgets: no provider, no timer, no network. Dart NOT compiled in the sandbox: the GitHub APK build is the first compile.

/// Colour of a tone word: 'good' green, 'bad' red, 'warn' amber, 'muted' grey, anything else the app accent.
Color owlToneOrMuted(AppPalette p, String tone) => tone == 'muted' ? p.textMuted : owlToneColor(p, tone);

/// A small pill with one plain word (CHAL RAHA, ULTA HO GAYA, PAPER ...). Never below 11 px. Pass [tone] or an exact [color].
class OwlStatusTag extends StatelessWidget {
  final String label;
  final String tone;
  final Color? color;
  final IconData? icon;

  const OwlStatusTag(this.label, {super.key, this.tone = '', this.color, this.icon});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final c = color ?? owlToneOrMuted(p, tone);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: c.withOpacity(0.14),
        borderRadius: BorderRadius.circular(100),
        border: Border.all(color: c.withOpacity(0.35)),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        if (icon != null) Padding(padding: const EdgeInsets.only(right: 4), child: Icon(icon, size: 12, color: c)),
        Flexible(child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 11, height: 1.15, fontWeight: FontWeight.w800, letterSpacing: 0.3, color: c))),
      ]),
    );
  }
}

/// How much proof stands behind a number, in plain words, from the SAMPLE COUNT only (it never says "works").
/// null = Unavailable, under [need] = Not enough data, under 3 x [need] = Early look, else Enough samples. Shows "7 of 30" when [showCount] is true.
class OwlEvidenceTag extends StatelessWidget {
  final int? samples;
  final int need;
  final bool showCount;

  const OwlEvidenceTag(this.samples, {super.key, this.need = 30, this.showCount = true});

  static String word(int? n, int need) {
    if (n == null) return 'Unavailable';
    if (n < need) return 'Not enough data';
    if (n < need * 3) return 'Early look';
    return 'Enough samples';
  }

  static String toneOf(int? n, int need) {
    if (n == null) return 'muted';
    if (n < need) return 'warn';
    if (n < need * 3) return '';
    return 'good';
  }

  @override
  Widget build(BuildContext context) {
    final n = samples;
    final text = (n != null && showCount) ? '${word(n, need)}  ·  $n of $need' : word(n, need);
    return OwlStatusTag(text, tone: toneOf(n, need));
  }
}

enum OwlCheck { yes, no, unavailable }

/// One line of a checklist: icon, plain label on the left, the value on the right. "Unavailable" is grey, never a guess.
class OwlCheckRow extends StatelessWidget {
  final String label;
  final String value;
  final OwlCheck check;

  const OwlCheckRow({super.key, required this.label, required this.value, this.check = OwlCheck.unavailable});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final c = check == OwlCheck.yes ? p.profit : (check == OwlCheck.no ? p.loss : p.textMuted);
    final icon = check == OwlCheck.yes ? Icons.check_circle : (check == OwlCheck.no ? Icons.cancel : Icons.remove_circle_outline);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 7),
      child: Row(children: [
        Icon(icon, size: 16, color: c),
        const SizedBox(width: 8),
        Expanded(child: Text(label, style: TextStyle(fontSize: 13, color: p.textPrimary))),
        const SizedBox(width: 8),
        Flexible(child: Text(value, maxLines: 1, overflow: TextOverflow.ellipsis, textAlign: TextAlign.right, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: c))),
      ]),
    );
  }
}

/// Top of a screen: the title and ONE plain line that says what the screen shows. [onInfo] adds an (i) button (the glossary comes in Part 33).
class OwlScreenIntro extends StatelessWidget {
  final String title;
  final String line;
  final VoidCallback? onInfo;

  const OwlScreenIntro({super.key, required this.title, this.line = '', this.onInfo});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            Text(title, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800, color: p.textPrimary)),
            if (line.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 2), child: Text(line, style: TextStyle(fontSize: 13, color: p.textSecondary))),
          ]),
        ),
        if (onInfo != null) IconButton(onPressed: onInfo, tooltip: 'What does this mean?', icon: Icon(Icons.info_outline, size: 20, color: p.textMuted), visualDensity: VisualDensity.compact),
      ]),
    );
  }
}
