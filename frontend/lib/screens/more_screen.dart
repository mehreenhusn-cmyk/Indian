import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../config_flags.dart';
import '../widgets/owl_pressable.dart';
import '../widgets/owl_route.dart';
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

  @override
  Widget build(BuildContext context) {
    final t = context.type;
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.l, AppSpacing.l, AppSpacing.xl),
          children: [
            Text('More', style: t.section.copyWith(fontSize: 22, fontWeight: FontWeight.bold)),
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
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: p.border, width: 1),
          ),
          child: Row(
            children: [
              Container(
                width: 38,
                height: 38,
                decoration: BoxDecoration(
                  color: p.accent.withOpacity(0.12),
                  borderRadius: BorderRadius.circular(10),
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
