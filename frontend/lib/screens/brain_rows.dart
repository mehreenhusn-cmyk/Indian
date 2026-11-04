import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';

/// R18: small shared pieces of the Brain screens. A coin row = coin name + time, ONE pill (the Brain answer) and ONE number (how many
/// indicator clashes). Everything with a sentence goes into the closed Details fold. Read-only, no state. Dart NOT compiled.

Color brainDecColor(AppPalette p, String d) => d.startsWith('OPEN') ? p.profit : (d == 'WAIT' ? p.warning : p.textMuted);

Color brainStormColor(AppPalette p, String s) => s.startsWith('RED') ? p.loss : (s.startsWith('GREEN') ? p.profit : p.textMuted);

/// Pill = a status word, never decoration.
Widget brainPill(AppPalette p, String t, Color c) => Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
      decoration: BoxDecoration(color: c.withOpacity(0.14), borderRadius: BorderRadius.circular(10)),
      child: Text(t, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: c)),
    );

/// Section heading (16) with an optional one-line caption (12).
Widget brainHeading(AppPalette p, String t, [String? sub]) => Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(t, style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: p.textPrimary)),
        if (sub != null) Text(sub, style: TextStyle(fontSize: 12, color: p.textMuted)),
      ]),
    );

/// One coin = one row (height 56 or more): name + time on the left, ONE pill (Brain answer), ONE number (clash count).
Widget brainCoinRow(AppPalette p, Map<String, dynamic> c, VoidCallback onTap) {
  final cl = c['clash'];
  final clash = cl is List ? cl.length : 0;
  final sym = '${c['symbol']}';
  final dec = '${c['decision']}';
  return InkWell(
    onTap: onTap,
    child: ConstrainedBox(
      constraints: const BoxConstraints(minHeight: 56),
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisAlignment: MainAxisAlignment.center, children: [
            Row(children: [
              Flexible(child: Text(sym, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: p.textPrimary))),
              if (sym.startsWith('BTC')) ...[const SizedBox(width: 6), brainPill(p, 'TEST COIN', p.textMuted)],
            ]),
            Text('${c['time']}', style: TextStyle(fontSize: 12, color: p.textMuted)),
          ]),
        ),
        brainPill(p, dec.replaceAll('_', ' '), brainDecColor(p, dec)),
        SizedBox(
          width: 40,
          child: Text('$clash', textAlign: TextAlign.right, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: clash > 0 ? p.warning : p.textMuted)),
        ),
        Icon(Icons.chevron_right, size: 18, color: p.textMuted),
      ]),
    ),
  );
}

/// ONE closed fold for all the text of a screen: title + a one-line summary, the sentences inside.
Widget brainDetails(AppPalette p, String title, String sub, List<Widget> kids) => OWLCard(
      padding: EdgeInsets.zero,
      child: Builder(builder: (ctx) => Theme(
        data: Theme.of(ctx).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          tilePadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 2),
          childrenPadding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
          expandedCrossAxisAlignment: CrossAxisAlignment.start,
          iconColor: p.textMuted,
          collapsedIconColor: p.textMuted,
          title: Text(title, style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: p.textPrimary)),
          subtitle: Text(sub, style: TextStyle(fontSize: 12, color: p.textMuted)),
          children: kids,
        ),
      )),
    );
