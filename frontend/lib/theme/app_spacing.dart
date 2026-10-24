/// Spacing and radius scale shared by all OWL widgets.
class AppSpacing {
  AppSpacing._();

  static const double xs = 4.0;
  static const double s = 8.0;
  static const double m = 12.0;
  static const double l = 16.0;
  static const double xl = 20.0;
  static const double xxl = 24.0;
  static const double section = 32.0;
  static const double huge = 40.0;

  // Layout rhythm (screens use these instead of ad-hoc 14/18/22 values)
  static const double screenPad = 16.0; // horizontal page padding
  static const double cardGap = 12.0; // gap between stacked cards
  static const double cardPad = 14.0; // inner padding of a compact card

  // Radii
  static const double radiusSmall = 8.0; // controls
  static const double radiusMedium = 14.0; // cards
  static const double radiusLarge = 20.0; // major surfaces
  static const double radiusPill = 100.0; // status badges
}
