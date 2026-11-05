import 'package:flutter/cupertino.dart' show CupertinoPageTransitionsBuilder;
import 'package:flutter/material.dart';
import 'app_colors.dart';
import 'app_spacing.dart';
import 'app_typography.dart';

// Every screen already imports app_theme.dart, so re-exporting the design
// tokens here means they get AppColors / AppSpacing / AppTypography without
// touching their imports.
export 'app_colors.dart';
export 'app_motion.dart';
export 'app_spacing.dart';
export 'app_typography.dart';

/// App-wide Material 3 theme configuration - true-black AMOLED exchange
/// terminal (dark) + Institutional (light) themes.
class AppTheme {
  static ThemeData get dark {
    final base = ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      fontFamily: AppTypography.family,
      fontFamilyFallback: AppTypography.familyFallback,
    );
    return base.copyWith(
      scaffoldBackgroundColor: AppColors.background,
      primaryColor: AppColors.accent,
      canvasColor: AppColors.background,
      dividerColor: AppColors.border,
      textTheme: base.textTheme.apply(
        bodyColor: AppColors.textPrimary,
        displayColor: AppColors.textPrimary,
      ),
      colorScheme: const ColorScheme.dark(
        primary: AppColors.accent,
        secondary: AppColors.purple,
        surface: AppColors.surfacePrimary,
        error: AppColors.negative,
      ),
      appBarTheme: AppBarTheme(
        backgroundColor: AppColors.background,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        iconTheme: IconThemeData(color: AppColors.textPrimary),
        titleTextStyle: TextStyle(
          color: AppColors.textPrimary,
          fontSize: 16,
          fontWeight: FontWeight.w600,
          fontFamily: AppTypography.family,
          fontFamilyFallback: AppTypography.familyFallback,
        ),
      ),
      pageTransitionsTheme: const PageTransitionsTheme(builders: {
        TargetPlatform.android: ZoomPageTransitionsBuilder(),
        TargetPlatform.iOS: CupertinoPageTransitionsBuilder(),
      }),
      cardTheme: CardThemeData(
        color: AppColors.surfaceElevated,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
          side: const BorderSide(color: AppColors.border, width: 1),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(style: _btn()),
      filledButtonTheme: FilledButtonThemeData(style: _btn()),
      outlinedButtonTheme: OutlinedButtonThemeData(style: _btn(side: const BorderSide(color: AppColors.border))),
      textButtonTheme: TextButtonThemeData(style: _btn(pad: const EdgeInsets.symmetric(horizontal: 10, vertical: 6))),
    );
  }

  /// E5: the one button look shared by both themes (shape, minimum height, label). Colors stay the theme's own.
  /// Uses styleFrom only, so it works on every Flutter 3.x version.
  static ButtonStyle _btn({BorderSide? side, EdgeInsetsGeometry? pad}) => side == null
      ? TextButton.styleFrom(
          shape: AppButtons.shape,
          minimumSize: const Size(0, AppButtons.minHeight),
          padding: pad ?? AppButtons.padding,
          textStyle: AppButtons.label,
          elevation: 0,
        )
      : OutlinedButton.styleFrom(
          shape: AppButtons.shape,
          minimumSize: const Size(0, AppButtons.minHeight),
          padding: pad ?? AppButtons.padding,
          textStyle: AppButtons.label,
          side: side,
        );

  /// Clean white "institutional" theme - matches the older app version's
  /// look (Positions tab, Dashboard equity card): white cards, crisp black
  /// text, a blue accent, soft grey borders instead of translucent glass.
  static ThemeData get light {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      fontFamily: AppTypography.family,
      fontFamilyFallback: AppTypography.familyFallback,
      scaffoldBackgroundColor: AppPalette.light.bg,
      primaryColor: AppPalette.light.accent,
      colorScheme: ColorScheme.light(
        primary: AppPalette.light.accent,
        secondary: AppPalette.light.purple,
        surface: AppPalette.light.surface,
        error: AppPalette.light.loss,
      ),
      appBarTheme: AppBarTheme(
        backgroundColor: AppPalette.light.bg,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        iconTheme: IconThemeData(color: AppPalette.light.textPrimary),
        titleTextStyle: TextStyle(
          color: AppPalette.light.textPrimary,
          fontSize: 16,
          fontWeight: FontWeight.w600,
          fontFamily: AppTypography.family,
          fontFamilyFallback: AppTypography.familyFallback,
        ),
      ),
      pageTransitionsTheme: const PageTransitionsTheme(builders: {
        TargetPlatform.android: ZoomPageTransitionsBuilder(),
        TargetPlatform.iOS: CupertinoPageTransitionsBuilder(),
      }),
      cardTheme: CardThemeData(
        color: AppPalette.light.surface,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
          side: BorderSide(color: AppPalette.light.glassBorder, width: 1),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(style: _btn()),
      filledButtonTheme: FilledButtonThemeData(style: _btn()),
      outlinedButtonTheme: OutlinedButtonThemeData(style: _btn(side: BorderSide(color: AppPalette.light.border))),
      textButtonTheme: TextButtonThemeData(style: _btn(pad: const EdgeInsets.symmetric(horizontal: 10, vertical: 6))),
    );
  }
}

/// Semantic color set that widgets read via `context.palette` instead of the
/// static AppColors constants, so the SAME widget code renders either theme.
/// Kept separate from AppColors (which stays const and dark-only) because
/// Dart default-parameter values must be compile-time constants and can't
/// depend on the current theme.
class AppPalette {
  final Color bg;
  final Color surface;
  final Color surfacePrimary;
  final Color surfaceElevated;
  final Color surfaceHigher;
  final Color border;
  final Color glassFill;
  final Color glassBorder;
  final Color glassHighlight;
  final Color accent;
  final Color profit;
  final Color loss;
  final Color purple;
  final Color owlEye;
  final Color warning;
  final Color textPrimary;
  final Color textSecondary;
  final Color textMuted;
  final Brightness brightness;

  const AppPalette({
    required this.bg,
    required this.surface,
    required this.surfacePrimary,
    required this.surfaceElevated,
    required this.surfaceHigher,
    required this.border,
    required this.glassFill,
    required this.glassBorder,
    required this.glassHighlight,
    required this.accent,
    required this.profit,
    required this.loss,
    required this.purple,
    required this.owlEye,
    required this.warning,
    required this.textPrimary,
    required this.textSecondary,
    required this.textMuted,
    required this.brightness,
  });

  /// Design-language aliases (positive/negative == profit/loss).
  Color get positive => profit;
  Color get negative => loss;

  static const AppPalette dark = AppPalette(
    bg: AppColors.background,
    surface: AppColors.surfacePrimary,
    surfacePrimary: AppColors.surfacePrimary,
    surfaceElevated: AppColors.surfaceElevated,
    surfaceHigher: AppColors.surfaceHigher,
    border: AppColors.border,
    glassFill: AppColors.glassFill,
    glassBorder: AppColors.glassBorder,
    glassHighlight: AppColors.glassHighlight,
    accent: AppColors.accent,
    profit: AppColors.profit,
    loss: AppColors.loss,
    purple: AppColors.purple,
    owlEye: AppColors.owlEye,
    warning: AppColors.warning,
    textPrimary: AppColors.textPrimary,
    textSecondary: AppColors.textSecondary,
    textMuted: AppColors.textMuted,
    brightness: Brightness.dark,
  );

  /// Crisp institutional white - same family of colors as the older app
  /// version's screenshots (white cards, near-black text, blue accent).
  static const AppPalette light = AppPalette(
    // Soft pearl-lavender canvas + white cards: modern, not plain white.
    // SR1a: off-white canvas so the white cards lift off it; hairline borders a little softer.
    bg: Color(0xFFF5F6F8), // P-A: cool off-white, same family as the cards (no blue paper)
    surface: Color(0xFFFFFFFF),
    surfacePrimary: Color(0xFFFFFFFF),
    surfaceElevated: Color(0xFFFFFFFF),
    surfaceHigher: Color(0xFFEDEFF2),
    border: Color(0xFFE3E6EB),
    glassFill: Color(0xFFFFFFFF),
    glassBorder: Color(0xFFE3E6EB),
    glassHighlight: Color(0x06000000),
    accent: Color(0xFF4F5DF0),
    profit: Color(0xFF16A34A),
    loss: Color(0xFFE11D2E),
    purple: Color(0xFF7C3AED),
    owlEye: Color(0xFFD97706),
    warning: Color(0xFFB45309),
    textPrimary: Color(0xFF10141C),
    textSecondary: Color(0xFF4B5670),
    textMuted: Color(0xFF8590A8),
    brightness: Brightness.light,
  );
}

/// `context.palette.accent` etc - reads whichever theme MaterialApp is
/// currently rendering (driven by AppProvider.themeMode), so a widget never
/// has to know or care which mode is active.
extension AppPaletteContext on BuildContext {
  AppPalette get palette =>
      Theme.of(this).brightness == Brightness.light
          ? AppPalette.light
          : AppPalette.dark;

  /// Theme-aware text styles: `context.type.metadata`, `.hero`, ...
  AppText get type => AppText(palette);
}

/// AppTypography's structural styles + the colors of the active palette.
class AppText {
  final AppPalette p;
  const AppText(this.p);

  TextStyle get hero =>
      AppTypography.heroNumber.copyWith(color: p.textPrimary);
  TextStyle get section =>
      AppTypography.sectionHeading.copyWith(color: p.textPrimary);
  TextStyle get primary =>
      AppTypography.primaryData.copyWith(color: p.textPrimary);
  TextStyle get secondary =>
      AppTypography.secondaryData.copyWith(color: p.textSecondary);
  TextStyle get metadata =>
      AppTypography.metadata.copyWith(color: p.textMuted);
  TextStyle get label =>
      AppTypography.label.copyWith(color: p.textMuted);
  /// Round 10b: 20 pt bold tabular number in the main text colour (stat tiles, verdict cards).
  TextStyle get number =>
      AppTypography.number.copyWith(color: p.textPrimary);
  /// Round 10b: 12 pt dimmed helper line.
  TextStyle get caption =>
      AppTypography.caption.copyWith(color: p.textMuted);
}
