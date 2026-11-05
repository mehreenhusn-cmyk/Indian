import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../utils/format.dart';

/// R28a (Part 8): the small pieces of the Positions "Close All" area that were cut or missing. Display only, they change nothing and call nothing.
///  - [CloseAllTotalLine]: ONE line right under the two Close All buttons: Profit + Loss = Net, so the two amounts on the buttons add up in front of the owner. The big header number stays the ONE total of the screen.
///  - [CloseAllPreviewList]: the list inside the "Close N positions?" dialog. It scrolls (the old column was cut off with many trades), a long coin name gets "...", an amount shrinks instead of being cut.
/// Dart NOT compiled (the APK build is the proof).
String closeAmt(double v) => v == 0 ? '0.00 USDT' : '${fmtSigned(v)} USDT';

class CloseAllTotalLine extends StatelessWidget {
  final double profit, loss;
  const CloseAllTotalLine({super.key, required this.profit, required this.loss});

  @override
  Widget build(BuildContext context) {
    final net = profit + loss;
    final m = context.type.metadata;
    return Padding(
      padding: const EdgeInsets.only(top: 4),
      child: FittedBox(
        fit: BoxFit.scaleDown,
        child: Text.rich(
          TextSpan(style: m, children: [
            TextSpan(text: 'Profit ${closeAmt(profit)}', style: m.copyWith(color: AppColors.profit)),
            const TextSpan(text: '   +   '),
            TextSpan(text: 'Loss ${closeAmt(loss)}', style: m.copyWith(color: AppColors.loss)),
            const TextSpan(text: '   =   '),
            TextSpan(text: 'Net ${closeAmt(net)}', style: m.copyWith(color: net >= 0 ? AppColors.profit : AppColors.loss, fontWeight: FontWeight.w800)),
          ]),
          maxLines: 1,
        ),
      ),
    );
  }
}

class CloseAllPreviewList extends StatelessWidget {
  final List<Map<String, dynamic>> positions;
  final double total;
  const CloseAllPreviewList({super.key, required this.positions, required this.total});

  @override
  Widget build(BuildContext context) {
    final maxH = math.min(300.0, MediaQuery.of(context).size.height * 0.4);
    Widget amount(double v, {bool bold = false}) => Flexible(
          child: FittedBox(
            fit: BoxFit.scaleDown,
            alignment: Alignment.centerRight,
            child: Text(closeAmt(v), maxLines: 1, style: TextStyle(color: v >= 0 ? AppColors.profit : AppColors.loss, fontWeight: bold ? FontWeight.bold : FontWeight.w500)),
          ),
        );
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ConstrainedBox(
          constraints: BoxConstraints(maxHeight: maxH),
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                for (final p in positions)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 2),
                    child: Row(children: [
                      Expanded(child: Text('${p['symbol']}', maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.secondary)),
                      const SizedBox(width: 8),
                      amount((p['pnl_usdt'] as num?)?.toDouble() ?? 0.0),
                    ]),
                  ),
              ],
            ),
          ),
        ),
        Divider(color: context.palette.border, height: 20),
        Row(children: [
          Text('Total', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(width: 8),
          amount(total, bold: true),
        ]),
      ],
    );
  }
}
