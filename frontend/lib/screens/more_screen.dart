import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../navigation/app_routes.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../config_flags.dart';
import '../widgets/font_switch_row.dart';
import '../widgets/owl_icon_tile.dart';
import '../widgets/owl_row.dart';
import '../widgets/owl_sentence.dart';
import '../widgets/owl_pressable.dart';
import '../widgets/owl_route.dart';
import '../widgets/report_download_card.dart';
import 'ai_report_screen.dart';
import 'app_problems_screen.dart';
import 'ping_tab_screen.dart';
import 'brain_chat_screen.dart';
import 'data_health_screen.dart';
import 'data_sources_screen.dart';
import 'simple_results_screen.dart';
import 'brain_today_screen.dart';
import 'screen_check_screen.dart';
import 'brain_dashboard_screen.dart';
import 'month_grid_screen.dart';
import 'reports_screen.dart';
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
    // P-E: every row has an icon TILE (tinted square). One tint per group: Trading tools = accent, Results = purple, System and Settings = grey. A different icon per row.
    final pal = context.palette;
    Widget Function(IconData, String, String, VoidCallback) tile(Color c) => (icon, title, sub, onTap) => OwlRow(title: title, sub: sub, leading: OwlIconTile(icon, c), onTap: onTap);
    final rT = tile(pal.accent), rR = tile(pal.purple), rS = tile(pal.textSecondary);
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.l, AppSpacing.l, AppSpacing.xl),
          children: [
            Text('More', style: context.type.section.copyWith(fontSize: 22, fontWeight: FontWeight.w800)),
            // Part 13c: groups in the order Trading tools, Results and reports, System, Settings. ONE card per group with thin lines (no box per row),
            // every row has a one-line purpose, row height follows the screen (AppScale). The doubles are gone: "System Health" (= Diagnostics) and "OwlSniper" (= the Sniper tab).
            const OwlSectionLabel('Trading tools'),
            OwlListCard(children: [
              rT(Icons.dashboard_outlined, 'Brain Dashboard', 'What the Brain decided and why', () => _open(context, 'Brain Dashboard', const BrainDashboardScreen())),
              rT(Icons.psychology_outlined, 'Brain', 'The Brain screen: states, books, paper trades', () => go(AppRoute.brain)),
              rT(Icons.smart_toy_rounded, 'Dual Bot', 'The Dual Bot paper book', () => go(AppRoute.dualBot)),
              rT(Icons.query_stats_outlined, 'Market', 'Prices, movers and market state', () => go(AppRoute.market)),
              rT(Icons.sensors_rounded, 'Signals', 'The signals the bots are looking at', () => go(AppRoute.signals)),
              rT(Icons.memory_rounded, 'AI', 'The AI helper page', () => go(AppRoute.ai)),
              rT(Icons.chat_bubble_outline, 'Ask the Brain', 'Ask a question in plain words', () => _open(context, 'Ask the Brain', const BrainChatScreen())),
              rT(Icons.health_and_safety_outlined, 'Data Health', 'Candles, missing data, is the Sniper learning', () => _open(context, 'Data Health', const DataHealthScreen())),
              rT(Icons.hub_outlined, 'Data and Learning', 'Who teaches the Sniper, live-test gate, auto runs', () => _open(context, 'Data and Learning', const DataSourcesScreen())),
              rT(Icons.image_search_outlined, 'Screenshot Check', 'Check a chart screenshot against the rules', () => _open(context, 'Screenshot Check', const ScreenCheckScreen())),
            ]),
            const OwlSectionLabel('Results and reports'),
            OwlListCard(children: [
              rR(Icons.today_outlined, 'Brain Today', 'Today in a few lines', () => _open(context, 'Brain Today', const BrainTodayScreen())),
              rR(Icons.timeline, 'Brain and Activity', 'A timeline of what the Brain did', () => _open(context, 'Brain and Activity', const TimelineScreen())),
              rR(Icons.grid_view_rounded, 'Month Calendar', 'Profit and loss for each day', () => _open(context, 'Month Calendar', const MonthGridScreen())),
              rR(Icons.emoji_events_outlined, 'Simple Results', 'Net, win rate and trades in plain words', () => _open(context, 'Simple Results', const SimpleResultsScreen())),
              rR(Icons.description_outlined, 'AI Report', 'A report to read or send to an AI', () => _open(context, 'AI Report', const AiReportScreen(), bare: true)),
              rR(Icons.receipt_long_outlined, 'Fees and tax report', 'Fees paid and a tax sheet', () => _open(context, 'Fees and tax report', const ReportsScreen())),
              rR(Icons.article_outlined, 'App report', 'One text file about the whole app', () => _download(context, const ReportDownloadCard())),
              rR(Icons.smart_toy_outlined, 'Dual Bot report', 'Every Dual Bot trade as one text file',
                  () => _download(
                      context,
                      const ReportDownloadCard(
                        title: 'Dual Bot report',
                        description: 'One text file for any AI: every Dual Bot trade with its exit and situation, the retest check, setups, lessons and totals.',
                        textPath: '/api/dual_lab/report',
                        savePath: '/api/dual_lab/report_save',
                        fileName: 'owl_dualbot_report.txt',
                      ))),
              rR(Icons.table_chart_outlined, 'Trades CSV', 'All finished trades for Sheets or Excel',
                  () => _download(
                      context,
                      const ReportDownloadCard(
                        title: 'Trades CSV',
                        description: 'All finished trades from the archive (nothing is ever deleted there) as one CSV file. Open it in Sheets or Excel, or send it to any AI.',
                        textPath: '/api/archive_export',
                        savePath: '/api/archive_export_save',
                        fileName: 'owl_trades.csv',
                        mimeType: 'text/csv',
                      ))),
            ]),
            const OwlSectionLabel('System'),
            OwlListCard(children: [
              rS(Icons.monitor_heart_outlined, 'Diagnostics', 'Connections, leaks and what is slow', () => go(AppRoute.diagnostics)),
              rS(Icons.bug_report_outlined, 'App Problems', 'A plain list of what is wrong, to copy', () => _open(context, 'App Problems', const AppProblemsScreen(), bare: true)),
              rS(Icons.bolt_rounded, 'Ping Lab', 'How fast the server answers', () => _open(context, 'Ping Lab', const PingTabScreen())),
              if (kShowStrategyDoctor)   // hidden by default (config_flags.dart): it opens Strategy Lab / Scan Lab and wakes their background work
                rS(Icons.medical_services_outlined, 'Strategy Doctor', 'Checks the strategy settings', () => _open(context, 'Strategy Doctor', const StrategyDoctorScreen(), bare: true)),
            ]),
            const OwlSectionLabel('Settings'),
            const FontSwitchRow(),
            OwlListCard(children: [
              rS(Icons.settings_rounded, 'Settings', 'Keys, limits, alerts and appearance', () => _open(context, 'Settings', const SettingsScreen())),
            ]),
          ],
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
