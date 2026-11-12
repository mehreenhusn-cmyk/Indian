import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';

/// Part 18B: the small table "MAIN BOT vs SNIPER" (open positions + P&L, Today, 7D, 30D, one row each, never added together).
/// Data = status['split'] from backend book_split.py. No split block (live mode, old backend) = nothing is drawn.
/// It lives in its own file because the first version sat inside dashboard_cockpit.dart, which the Dashboard does not use.
class MainSniperTable extends StatelessWidget {
  const MainSniperTable({super.key});

  @override
  Widget build(BuildContext context) {
    return Selector<AppProvider, String>(
      selector: (_, p) => '${p.splitBlock?['generated']}|${p.statsMode}',
      builder: (context, _, __) {
        final prov = context.read<AppProvider>();
        final sp = prov.statsMode == 'live' ? null : prov.splitBlock;
        if (sp == null) return const SizedBox.shrink();
        final p = context.palette;
        double nv(Map<String, dynamic> m, String k) => (m[k] as num?)?.toDouble() ?? 0.0;
        Color pc(double v) => v == 0 ? p.textPrimary : (v > 0 ? p.profit : p.loss);
        Widget cell(String t, {Color? color, bool bold = false, int flex = 1}) => Expanded(
              flex: flex,
              child: Text(t, maxLines: 1, overflow: TextOverflow.ellipsis, textAlign: flex == 2 ? TextAlign.left : TextAlign.right,
                  style: context.type.metadata.copyWith(color: color ?? p.textSecondary, fontWeight: bold ? FontWeight.w700 : FontWeight.w500)),
            );
        Widget row(String name, Map<String, dynamic> m) => Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(children: [
                cell(name, bold: true, flex: 2, color: p.textPrimary),
                cell('${(m['n'] as num?)?.toInt() ?? 0} · ${fmtSigned(nv(m, 'pnl'))}', color: pc(nv(m, 'pnl'))),
                cell(fmtSigned(nv(m, 'today_pnl')), color: pc(nv(m, 'today_pnl'))),
                cell(fmtSigned(nv(m, 'd7_pnl')), color: pc(nv(m, 'd7_pnl'))),
                cell(fmtSigned(nv(m, 'd30_pnl')), color: pc(nv(m, 'd30_pnl'))),
              ]),
            );
        final partial = sp['d7_partial'] == true || sp['d30_partial'] == true;
        return Container(
          padding: const EdgeInsets.only(bottom: AppSpacing.m),
          decoration: BoxDecoration(border: Border(bottom: BorderSide(color: p.border))),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('MAIN BOT vs SNIPER (apart, never added)', style: AppTypography.eyebrow.copyWith(color: p.textMuted, fontSize: 9.5)),
            const SizedBox(height: 6),
            Row(children: [
              cell('', flex: 2),
              cell('OPEN', color: p.textMuted),
              cell('TODAY', color: p.textMuted),
              cell('7D', color: p.textMuted),
              cell('30D', color: p.textMuted),
            ]),
            row('MAIN', prov.splitGroup('main')),
            row('SNIPER', prov.splitGroup('sniper')),
            if (partial)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text('7D / 30D are partial: the book keeps only the last 1500 trades.', style: context.type.metadata.copyWith(color: p.textMuted)),
              ),
          ]),
        );
      },
    );
  }
}
