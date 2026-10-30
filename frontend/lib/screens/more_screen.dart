import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../navigation/app_routes.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../config_flags.dart';
import '../widgets/owl_pressable.dart';
import '../widgets/owl_route.dart';
import '../widgets/report_download_card.dart';
import 'ai_report_screen.dart';
import 'ping_tab_screen.dart';
import 'settings_screen.dart';
import 'strategy_doctor_screen.dart';
import 'tag_lab_screen.dart';

/// "More" tab: everything that is not used all day, in three small groups.
/// Each row opens a full screen with a back arrow. Nothing here is new logic, these are the
/// same screens as before, just moved out of the bottom bar.
class MoreScreen extends StatelessWidget {
  const MoreScreen({super.key});

  void _open(BuildContext context, String title, Widget screen, {bool bare = false}) {
    Navigator.of(context).push(
      OwlRoute(builder: (_) => bare ? screen : _SubPage(title: title, child: screen)),
    );
  }

  /// UI-D: opens one download card in a bottom sheet (same card the Dual Bot and Settings use).
  void _download(BuildContext context, ReportDownloadCard card) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (_) => Padding(padding: const EdgeInsets.all(12), child: SafeArea(child: card)),
    );
  }

  @override
  Widget build(BuildContext context) {
    final t = context.type;
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.l, AppSpacing.l, AppSpacing.xl),
          children: [
            Text('More', style: t.section.copyWith(fontSize: 22, fontWeight: FontWeight.w800)),
            const SizedBox(height: AppSpacing.l),
            _label(context, 'MORE TABS'),
            _row(context, Icons.sensors_rounded, 'Signals', 'Signals and alerts', () => context.read<AppProvider>().goToRoute(AppRoute.signals)),
            _row(context, Icons.smart_toy_rounded, 'Dual Bot', 'Dual Bot trades, desk and reports', () => context.read<AppProvider>().goToRoute(AppRoute.dualBot)),
            _row(context, Icons.memory_rounded, 'AI', 'AI Vision and the AI tab', () => context.read<AppProvider>().goToRoute(AppRoute.ai)),
            const SizedBox(height: AppSpacing.l),
            _label(context, 'TRADING TOOLS'),
            _row(context, Icons.hub_outlined, 'Tag Lab', 'Test ideas on old candles',
                () => _open(context, 'Tag Lab', const TagLabScreen(), bare: true)),
            if (kShowStrategyDoctor)   // hidden by default (config_flags.dart): it opens Strategy Lab / Scan Lab and wakes their background work
              _row(context, Icons.medical_services_outlined, 'Strategy Doctor', 'Why trades win or lose',
                  () => _open(context, 'Strategy Doctor', const StrategyDoctorScreen(), bare: true)),
            _row(context, Icons.description_outlined, 'AI Report', 'Save a report you can share with any AI',
                () => _open(context, 'AI Report', const AiReportScreen(), bare: true)),
            const SizedBox(height: AppSpacing.l),
            _label(context, 'DOWNLOADS'),
            _row(context, Icons.article_outlined, 'App report', 'One text file about the whole app',
                () => _download(context, const ReportDownloadCard())),
            _row(context, Icons.smart_toy_outlined, 'Dual Bot report', 'Every trade, setups and lessons',
                () => _download(
                    context,
                    const ReportDownloadCard(
                      title: 'Dual Bot report',
                      description:
                          'One text file for any AI: every Dual Bot trade with its exit and situation, the retest check, setups, lessons and totals.',
                      textPath: '/api/dual_lab/report',
                      savePath: '/api/dual_lab/report_save',
                      fileName: 'owl_dualbot_report.txt',
                    ))),
            _row(context, Icons.table_chart_outlined, 'Trades CSV', 'All finished trades, opens in any sheet app',
                () => _download(
                    context,
                    const ReportDownloadCard(
                      title: 'Trades CSV',
                      description:
                          'All finished trades from the archive (nothing is ever deleted there) as one CSV file. Open it in Sheets or Excel, or send it to any AI.',
                      textPath: '/api/archive_export',
                      savePath: '/api/archive_export_save',
                      fileName: 'owl_trades.csv',
                      mimeType: 'text/csv',
                    ))),
            const SizedBox(height: AppSpacing.l),
            _label(context, 'LIVE DATA'),
            _row(context, Icons.bolt_rounded, 'Ping Lab', 'Volume pings: which coins are heating up',
                () => _open(context, 'Ping Lab', const PingTabScreen())),
            const SizedBox(height: AppSpacing.l),
            _label(context, 'APP'),
            _row(context, Icons.settings_rounded, 'Settings', 'Trade risk, AI keys, sounds, backup',
                () => _open(context, 'Settings', const SettingsScreen())),
          ],
        ),
      ),
    );
  }

  Widget _label(BuildContext context, String text) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.only(left: 4, bottom: AppSpacing.s),
      child: Text(
        text,
        style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, letterSpacing: 0.8, color: p.textMuted),
      ),
    );
  }

  Widget _row(BuildContext context, IconData icon, String title, String sub, VoidCallback onTap) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.s),
      child: OWLPressable(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          decoration: BoxDecoration(
            color: p.surface,
            borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
            border: Border.all(color: p.border, width: 1),
            boxShadow: p.brightness == Brightness.light
                ? [BoxShadow(color: const Color(0xFF101828).withOpacity(0.05), blurRadius: 16, offset: const Offset(0, 4))]
                : null,
          ),
          child: Row(
            children: [
              Container(
                width: 38,
                height: 38,
                decoration: BoxDecoration(
                  color: p.accent.withOpacity(0.10),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(icon, size: 20, color: p.accent),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: p.textPrimary)),
                    const SizedBox(height: 2),
                    Text(sub, style: TextStyle(fontSize: 12, color: p.textMuted)),
                  ],
                ),
              ),
              Icon(Icons.chevron_right_rounded, size: 22, color: p.textMuted),
            ],
          ),
        ),
      ),
    );
  }
}

/// Plain page with a title and a back arrow, for screens that have no app bar of their own.
class _SubPage extends StatelessWidget {
  final String title;
  final Widget child;
  const _SubPage({required this.title, required this.child});

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
