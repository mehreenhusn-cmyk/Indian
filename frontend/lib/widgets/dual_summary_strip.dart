import 'dart:ui' show FontFeature;

import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../utils/format.dart';
import 'dual_trade_card.dart';

/// Top of the Dual Bot "Now" tab: one compact status bar (bot state, today P&L, trust, open count)
/// and a strip of 3 small cards: Today / Quality / Open Risk. Only shows numbers the screen already has.
/// [brain] is the Smart Brain opinion per trade key (coin|timeframe|time) -> {clean, div, verdict, text}.
class DualSummaryStrip extends StatelessWidget {
  final bool running;
  final bool learned;
  final String stateText;
  final String trust; // 'earned' / 'not_yet' / 'learning' / '' (no Brain reply yet)
  final Map<String, dynamic> today; // summary.today from /api/dual_lab
  final List<Map<String, dynamic>> open; // open trades (rows with s, f, t, d, live_now ...)
  final Map<String, dynamic> brain;

  const DualSummaryStrip({
    super.key,
    required this.running,
    required this.learned,
    required this.stateText,
    required this.trust,
    required this.today,
    required this.open,
    required this.brain,
  });

  static double _n(dynamic v) => v is num ? v.toDouble() : 0.0;
  static const _tab = [FontFeature.tabularFigures()];

  Map<String, dynamic>? _op(Map<String, dynamic> t) {
    final o = brain['${t['s']}|${t['f']}|${t['t']}'];
    return o is Map ? Map<String, dynamic>.from(o) : null;
  }

  Widget _chip(String text, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: c.withOpacity(0.12), borderRadius: BorderRadius.circular(8)),
        child: Text(text, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: c)),
      );

  Widget _mini(AppPalette p, {required String label, required String big, required Color bigColor, required String small}) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.fromLTRB(10, 9, 10, 9),
        decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(12), border: Border.all(color: p.border)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w700, color: p.textMuted, letterSpacing: 0.4)),
          const SizedBox(height: 3),
          FittedBox(
            fit: BoxFit.scaleDown,
            alignment: Alignment.centerLeft,
            child: Text(big, maxLines: 1, style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: bigColor, fontFeatures: _tab)),
          ),
          const SizedBox(height: 2),
          Text(small, maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 10.5, color: p.textMuted, height: 1.25)),
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;

    // ---- Today ----
    final total = _n(today['total']);
    final locked = today.containsKey('realized') ? _n(today['realized']) : total;
    final closed = _n(today['closed']).toInt();
    final wins = _n(today['wins']).toInt();
    final winPct = closed > 0 ? (100 * wins / closed).round() : null;
    final todayColor = locked >= 0 ? p.profit : p.loss;

    // ---- Quality: how many open trades the Brain rates good, and their average clean score ----
    var good = 0, bad = 0, rated = 0;
    double cleanSum = 0;
    for (final t in open) {
      final o = _op(t);
      if (o == null || o['clean'] is! num) continue;
      rated++;
      cleanSum += _n(o['clean']);
      final g = DualTradeCard.quality(o);
      if (g == 'good') good++;
      if (g == 'bad') bad++;
    }
    final goodPct = rated > 0 ? (100 * good / rated).round() : null;
    final avgClean = rated > 0 ? (cleanSum / rated).round() : null;
    final qColor = goodPct == null ? p.textMuted : (goodPct >= 60 ? p.profit : (goodPct >= 35 ? p.warning : p.loss));

    // ---- Open risk: count, floating P&L, long / short ----
    final nOpen = today.isNotEmpty ? _n(today['open']).toInt() : open.length;
    final nLong = today.isNotEmpty ? _n(today['open_long']).toInt() : open.where((t) => _n(t['d']) > 0).length;
    final floating = _n(today['open_pnl']);
    final floatColor = floating >= 0 ? p.profit : p.loss;

    final trustColor = trust == 'earned' ? p.profit : (trust == 'not_yet' ? p.warning : p.textMuted);
    final trustText = trust == 'earned' ? 'Trust: earned' : (trust == 'not_yet' ? 'Trust: not yet' : (trust == 'learning' ? 'Trust: learning' : 'Trust: --'));
    final dot = running ? p.profit : p.textMuted;

    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        // ---- status bar ----
        Container(
          padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
          decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(12), border: Border.all(color: p.border)),
          child: Row(children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Icon(Icons.circle, size: 9, color: dot),
                  const SizedBox(width: 6),
                  Flexible(
                    child: Text(running ? (learned ? 'Running - learned' : 'Running - learning') : stateText,
                        maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: p.textPrimary)),
                  ),
                ]),
                const SizedBox(height: 2),
                FittedBox(
                  fit: BoxFit.scaleDown,
                  alignment: Alignment.centerLeft,
                  child: Text('${fmtSigned(locked)} USDT',
                      maxLines: 1, style: TextStyle(fontSize: 24, fontWeight: FontWeight.w900, color: todayColor, fontFeatures: _tab)),
                ),
                Text('closed today (locked in)', style: TextStyle(fontSize: 10.5, color: p.textMuted)),
                if (nOpen > 0) Text('open trades now ${fmtSigned(floating)} (not locked) = ${fmtSigned(total)} in total', style: TextStyle(fontSize: 10.5, color: p.textMuted)),
              ]),
            ),
            Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
              _chip(trustText, trustColor),
              const SizedBox(height: 6),
              _chip('$nOpen open', nOpen > 0 ? p.accent : p.textMuted),
            ]),
          ]),
        ),
        const SizedBox(height: 8),
        // ---- 3 summary cards ----
        IntrinsicHeight(
          child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          _mini(p,
              label: 'TODAY',
              big: winPct == null ? '--' : '$winPct% won',
              bigColor: winPct == null ? p.textMuted : (winPct >= 50 ? p.profit : p.loss),
              small: '$closed closed, ${_n(today['opened']).toInt()} opened'),
          const SizedBox(width: 8),
          _mini(p,
              label: 'QUALITY',
              big: goodPct == null ? '--' : '$goodPct% good',
              bigColor: qColor,
              small: rated == 0 ? 'Brain has no opinion yet' : 'avg clean $avgClean, $bad bad of $rated'),
          const SizedBox(width: 8),
          _mini(p,
              label: 'OPEN NOW (NOT LOCKED)',
              big: '${fmtSigned(floating)}',
              bigColor: nOpen == 0 ? p.textMuted : floatColor,
              small: nOpen == 0 ? 'nothing open' : '$nOpen open: $nLong long, ${nOpen - nLong} short'),
          ]),
        ),
      ]),
    );
  }
}
