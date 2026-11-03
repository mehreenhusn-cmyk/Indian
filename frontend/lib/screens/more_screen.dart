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
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.l, AppSpacing.l, AppSpacing.xl),
          children: [
            Row(children: [
              Icon(Icons.settings_rounded, size: 22, color: context.palette.textMuted),
              const SizedBox(width: 8),
              Text('Settings and tools', style: t.section.copyWith(fontSize: 22, fontWeight: FontWeight.w800)),
            ]),
            const SizedBox(height: AppSpacing.l),
            _row(context, Icons.bug_report_outlined, 'App Problems', 'Everything that fails or is slow, in one list: take a screenshot or press Copy all and send it (read-only)',
                () => _open(context, 'App Problems', const AppProblemsScreen(), bare: true)),
            const SizedBox(height: AppSpacing.l),
            _label(context, 'MORE TABS'),
            _row(context, Icons.dashboard_outlined, 'Brain Dashboard', 'One home page: today net, Brain vs Current Bot 30 days, open trades, daily loss cap, recent days (read-only, live stays locked)',
                () => _open(context, 'Brain Dashboard', const BrainDashboardScreen())),
            _row(context, Icons.query_stats_outlined, 'Market', 'All pairs and prices', () => context.read<AppProvider>().goToRoute(AppRoute.market)),
            _row(context, Icons.psychology_outlined, 'Brain', 'Brain Trader: today, signals, paper trades', () => context.read<AppProvider>().goToRoute(AppRoute.brain)),
            _row(context, Icons.sensors_rounded, 'Signals', 'Signals and alerts', () => context.read<AppProvider>().goToRoute(AppRoute.signals)),
            _row(context, Icons.smart_toy_rounded, 'Dual Bot', 'Dual Bot trades, desk and reports', () => context.read<AppProvider>().goToRoute(AppRoute.dualBot)),
            _row(context, Icons.memory_rounded, 'AI', 'AI Vision and the AI tab', () => context.read<AppProvider>().goToRoute(AppRoute.ai)),
            const SizedBox(height: AppSpacing.l),
            _label(context, 'TOOLS'),
            if (kShowStrategyDoctor)   // hidden by default (config_flags.dart): it opens Strategy Lab / Scan Lab and wakes their background work
              _row(context, Icons.medical_services_outlined, 'Strategy Doctor', 'Why trades win or lose',
                  () => _open(context, 'Strategy Doctor', const StrategyDoctorScreen(), bare: true)),
            _row(context, Icons.description_outlined, 'AI Report', 'Save a report you can share with any AI',
                () => _open(context, 'AI Report', const AiReportScreen(), bare: true)),
            _row(context, Icons.receipt_long_outlined, 'Fees and tax report', 'Gross, fees, net and a tax estimate (read-only)',
                () => _open(context, 'Fees and tax report', const ReportsScreen())),
            _row(context, Icons.image_search_outlined, 'Screenshot Check', 'Type a coin and time: the 2 indicators, its own history and a labelled OPINION (read-only)',
                () => _open(context, 'Screenshot Check', const ScreenCheckScreen())),
            _row(context, Icons.chat_bubble_outline, 'Ask the Brain', 'Ask in your words (Claude answers only from your saved data, never an order)',
                () => _open(context, 'Ask the Brain', const BrainChatScreen())),
            _row(context, Icons.today_outlined, 'Brain Today', 'What the Brain did today, each coin in plain words, why some coins have no data (pretend money, read-only)',
                () => _open(context, 'Brain Today', const BrainTodayScreen())),
            _row(context, Icons.grid_view_rounded, 'Month Calendar', 'A whole month as a grid: Brain net of every day (green / red), month net of Brain and Current Bot, best and worst day, running line (read-only)',
                () => _open(context, 'Month Calendar', const MonthGridScreen())),
            _row(context, Icons.timeline, 'Brain and Activity', 'One day as a timeline, newest first: what the Brain took, waited on or skipped, and what the Current Bot opened and closed, side by side in time. Coins where both acted (read-only)',
                () => _open(context, 'Brain and Activity', const TimelineScreen())),
            _row(context, Icons.monitor_heart_outlined, 'System Health', 'Real facts only: backend, candle feed, Brain tick, safety, CPU, RAM, disk. What cannot be measured says NOT AVAILABLE (read-only)',
                () => _open(context, 'System Health', const SystemHealthScreen())),
            _row(context, Icons.gps_fixed, 'OwlSniper', 'Trending or sideways banner, order cards that pass or are blocked, the 85% win-chance floor proven on unseen days (watch only, no order is sent)',
                () => _open(context, 'OwlSniper', const SniperScreen())),
            _row(context, Icons.emoji_events_outlined, 'Simple Results', 'One word: is the Brain making money? Net, worst dip, losing streak, equity line, what to USE and what to STOP (read-only)',
                () => _open(context, 'Simple Results', const SimpleResultsScreen())),
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
