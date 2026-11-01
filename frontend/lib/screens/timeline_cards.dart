import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';
import 'learning_progress_cards.dart';

/// Part M4b: cards of the Brain and Activity timeline screen (read-only, route brain_timeline). Dart NOT compiled (the APK build is the proof).

Widget tlKv(AppPalette p, String big, String label, [Color? c]) => Expanded(
      child: Column(children: [
        Text(big, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: c ?? p.textPrimary)),
        const SizedBox(height: 2),
        Text(label, textAlign: TextAlign.center, style: TextStyle(fontSize: 10.5, color: p.textMuted)),
      ]),
    );

/// Two blocks side by side in time: what the Brain did today and what the Current Bot did today. Never added together.
Widget tlSummary(AppPalette p, Map<String, dynamic> r) {
  final b = lpMap(r['brain']);
  final k = lpMap(r['bot']);
  return OWLCard(
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('Owl Brain', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.accent)),
      const SizedBox(height: 8),
      Row(children: [
        tlKv(p, '${lpNum(b['took']).toInt()}', 'Took'),
        tlKv(p, '${lpNum(b['waited']).toInt()}', 'Waited'),
        tlKv(p, '${lpNum(b['skipped']).toInt()}', 'Skipped'),
        tlKv(p, '${lpNum(b['closed']).toInt()}', 'Closed'),
        tlKv(p, lpSg(b['net_usdt']), 'Net USDT', lpNet(p, b['net_usdt'])),
      ]),
      if (lpNum(b['no_opinion']) > 0 || lpNum(b['wait_skip_cut']) > 0)
        Padding(
          padding: const EdgeInsets.only(top: 6),
          child: Text('${lpNum(b['no_opinion']).toInt()} coin checks had no opinion (only counted). ${lpNum(b['wait_skip_cut']).toInt()} older WAIT / SKIP lines are not listed.', style: TextStyle(fontSize: 11, color: p.textMuted)),
        ),
      const SizedBox(height: 14),
      Text('Current Bot', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textSecondary)),
      const SizedBox(height: 8),
      if (k['ok'] == false)
        Text('The bot trade files could not be read right now.', style: TextStyle(fontSize: 12, color: p.warning))
      else
        Row(children: [
          tlKv(p, '${lpNum(k['opened']).toInt()}', 'Opened'),
          tlKv(p, '${lpNum(k['closed']).toInt()}', 'Closed'),
          tlKv(p, lpSg(k['net_usdt']), 'Net USDT', lpNet(p, k['net_usdt'])),
        ]),
    ]),
  );
}

/// Coins, both-acted first: "Brain took / skipped, bot traded" with each side's closed net (apart).
Widget tlCoins(AppPalette p, Map<String, dynamic> r) {
  final cs = lpList(r['coins']);
  if (cs.isEmpty) return const SizedBox.shrink();
  return OWLCard(
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('Coins today', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary)),
      const SizedBox(height: 4),
      Text('BOTH = the Brain and the bot both acted on this coin today.', style: TextStyle(fontSize: 11, color: p.textMuted)),
      const SizedBox(height: 8),
      for (final c in cs)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Row(children: [
            Expanded(
              flex: 4,
              child: Row(children: [
                Flexible(child: Text('${c['symbol']}', overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: p.textPrimary))),
                if (c['both'] == true)
                  Container(
                    margin: const EdgeInsets.only(left: 6),
                    padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
                    decoration: BoxDecoration(color: p.accent.withOpacity(0.15), borderRadius: BorderRadius.circular(6)),
                    child: Text('BOTH', style: TextStyle(fontSize: 9.5, fontWeight: FontWeight.w800, color: p.accent)),
                  ),
              ]),
            ),
            Expanded(flex: 3, child: Text('Brain ${lpSg(c['brain_net_usdt'])}', textAlign: TextAlign.right, style: TextStyle(fontSize: 11.5, color: lpNet(p, c['brain_net_usdt'])))),
            Expanded(flex: 3, child: Text('Bot ${lpSg(c['bot_net_usdt'])}', textAlign: TextAlign.right, style: TextStyle(fontSize: 11.5, color: lpNet(p, c['bot_net_usdt'])))),
          ]),
        ),
    ]),
  );
}

Color _kindColor(AppPalette p, Map<String, dynamic> e) {
  switch ('${e['kind']}') {
    case 'TAKE':
    case 'OPEN':
      return p.accent;
    case 'CLOSE':
      return lpNum(e['net_usdt']) >= 0 ? p.profit : p.loss;
    case 'WAIT':
      return p.warning;
    default:
      return p.textMuted;
  }
}

/// ONE line of the timeline: time (IST), who, what, coin and side, and the net when it is a close.
Widget tlEvent(AppPalette p, Map<String, dynamic> e) {
  final brain = e['who'] == 'BRAIN';
  final c = _kindColor(p, e);
  final net = e['net_usdt'];
  return Container(
    margin: const EdgeInsets.symmetric(vertical: 3),
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
    decoration: BoxDecoration(color: c.withOpacity(0.07), borderRadius: BorderRadius.circular(8)),
    child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Container(width: 3, height: 34, margin: const EdgeInsets.only(right: 8), decoration: BoxDecoration(color: brain ? p.accent : p.textMuted, borderRadius: BorderRadius.circular(2))),
      SizedBox(width: 44, child: Text('${e['ist']}', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: p.textSecondary))),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${brain ? 'BRAIN' : 'BOT'} - ${e['kind']} - ${e['symbol']} ${e['side']}${e['interval'] == null ? '' : ' ${e['interval']}'}', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: c)),
          const SizedBox(height: 2),
          Text('${e['text']}', style: TextStyle(fontSize: 11.5, color: p.textPrimary)),
          if (e['reason'] != null) Text('${e['reason']}', maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 10.5, color: p.textMuted)),
        ]),
      ),
      if (net != null) Text(lpSg(net), style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: lpNet(p, net))),
    ]),
  );
}
