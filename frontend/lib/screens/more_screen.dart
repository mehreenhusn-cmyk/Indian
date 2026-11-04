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
import 'app_problems_screen.dart';
import 'ping_tab_screen.dart';
import 'brain_chat_screen.dart';
import 'simple_results_screen.dart';
import 'brain_today_screen.dart';
import 'screen_check_screen.dart';
import 'brain_dashboard_screen.dart';
import 'system_health_screen.dart';
import 'month_grid_screen.dart';
import 'reports_screen.dart';
import 'sniper_screen.dart';
import 'settings_screen.dart';
import 'strategy_doctor_screen.dart';
import 'timeline_screen.dart';

/// R20: grouped in 5 headings + App Problems on top, ONE line per row (icon + name, no grey sub text), rows 56 high, title 20, heading 13, row 15 (text scale of 06_FRONTEND_SPEC).
/// The power / pause button is NOT on this page: it sits in the top ticker bar, far from the gear (Part 14). English only.
/// Round 10b: the "More" page becomes the SETTINGS AND TOOLS page (opened by the top-bar gear since Round 11). Every study moved to the Study Lab hub; what stays
/// is Market and Brain (they left the bottom bar), tools whose new tab is not built yet (they leave this page when that tab lands), downloads, live data and settings.
/// Old text: "More" tab: everything that is not used all day, in small groups.
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
    final go = context.read<AppProvider>().goToRoute;
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.l, AppSpacing.l, AppSpacing.xl),
          children: [
            Row(children: [
              Icon(Icons.settings_rounded, size: 22, color: context.palette.textPrimary),
              const SizedBox(width: 8),
              Text('Settings and tools', style: t.section.copyWith(fontSize: 20, fontWeight: FontWeight.w700)),
            ]),
            const SizedBox(height: AppSpacing.l),
            _row(context, Icons.bug_report_outlined, 'App Problems', () => _open(context, 'App Problems', const AppProblemsScreen(), bare: true)),
            const SizedBox(height: AppSpacing.l),
            _label(context, 'TABS'),
            _row(context, Icons.dashboard_outlined, 'Brain Dashboard', () => _open(context, 'Brain Dashboard', const BrainDashboardScreen())),
            _row(context, Icons.query_stats_outlined, 'Market', () => go(AppRoute.market)),
            _row(context, Icons.psychology_outlined, 'Brain', () => go(AppRoute.brain)),
            _row(context, Icons.sensors_rounded, 'Signals', () => go(AppRoute.signals)),
            _row(context, Icons.smart_toy_rounded, 'Dual Bot', () => go(AppRoute.dualBot)),
            _row(context, Icons.memory_rounded, 'AI', () => go(AppRoute.ai)),
            const SizedBox(height: AppSpacing.l),
            _label(context, 'BRAIN'),
            _row(context, Icons.today_outlined, 'Brain Today', () => _open(context, 'Brain Today', const BrainTodayScreen())),
            _row(context, Icons.timeline, 'Brain and Activity', () => _open(context, 'Brain and Activity', const TimelineScreen())),
            _row(context, Icons.grid_view_rounded, 'Month Calendar', () => _open(context, 'Month Calendar', const MonthGridScreen())),
            _row(context, Icons.emoji_events_outlined, 'Simple Results', () => _open(context, 'Simple Results', const SimpleResultsScreen())),
            _row(context, Icons.chat_bubble_outline, 'Ask the Brain', () => _open(context, 'Ask the Brain', const BrainChatScreen())),
            _row(context, Icons.image_search_outlined, 'Screenshot Check', () => _open(context, 'Screenshot Check', const ScreenCheckScreen())),
            const SizedBox(height: AppSpacing.l),
            _label(context, 'SNIPER AND HEALTH'),
            _row(context, Icons.gps_fixed, 'OwlSniper', () => _open(context, 'OwlSniper', const SniperScreen())),
            _row(context, Icons.monitor_heart_outlined, 'System Health', () => _open(context, 'System Health', const SystemHealthScreen())),
            const SizedBox(height: AppSpacing.l),
            _label(context, 'REPORTS AND TOOLS'),
            if (kShowStrategyDoctor)   // hidden by default (config_flags.dart): it opens Strategy Lab / Scan Lab and wakes their background work
              _row(context, Icons.medical_services_outlined, 'Strategy Doctor', () => _open(context, 'Strategy Doctor', const StrategyDoctorScreen(), bare: true)),
            _row(context, Icons.description_outlined, 'AI Report', () => _open(context, 'AI Report', const AiReportScreen(), bare: true)),
            _row(context, Icons.receipt_long_outlined, 'Fees and tax report', () => _open(context, 'Fees and tax report', const ReportsScreen())),
            _row(context, Icons.article_outlined, 'App report', () => _download(context, const ReportDownloadCard())),
            _row(context, Icons.smart_toy_outlined, 'Dual Bot report',
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
            _row(context, Icons.table_chart_outlined, 'Trades CSV',
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
            _label(context, 'DATA AND APP'),
            _row(context, Icons.bolt_rounded, 'Ping Lab', () => _open(context, 'Ping Lab', const PingTabScreen())),
            _row(context, Icons.settings_rounded, 'Settings', () => _open(context, 'Settings', const SettingsScreen())),
          ],
        ),
      ),
    );
  }

  Widget _label(BuildContext context, String text) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.only(left: 4, bottom: AppSpacing.s),
      child: Text(text, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, letterSpacing: 0.8, color: p.textPrimary)),
    );
  }

  /// ONE line: icon + name + chevron, at least 56 high. No second line of grey text.
  Widget _row(BuildContext context, IconData icon, String title, VoidCallback onTap) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.s),
      child: OWLPressable(
        onTap: onTap,
        child: Container(
          constraints: const BoxConstraints(minHeight: 56),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
          decoration: BoxDecoration(
            color: p.surface,
            borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
            border: Border.all(color: p.border, width: 1),
          ),
          child: Row(
            children: [
              Container(
                width: 36,
                height: 36,
                decoration: BoxDecoration(color: p.accent.withOpacity(0.10), borderRadius: BorderRadius.circular(12)),
                child: Icon(icon, size: 20, color: p.accent),
              ),
              const SizedBox(width: 12),
              Expanded(child: Text(title, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: p.textPrimary))),
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
