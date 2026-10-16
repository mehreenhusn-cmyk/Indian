import 'dart:io';
import 'owl_terminal_logo.dart';

/// Writes the OWL logo to a PNG file (e.g. for the Android launcher icon).
///
/// Kept in its own file because it imports dart:io - the logo WIDGET file
/// must stay free of it so nothing in the widget tree breaks a web build.
///
/// Example (call from any async context, e.g. a temporary debug button):
///   await saveOwlLogoToPngFile('/storage/emulated/0/Download/owl_launcher_512.png');
Future<File> saveOwlLogoToPngFile(
  String filePath, {
  int size = 512,
  bool withBackground = true,
  bool glowing = true,
}) async {
  final bytes = await OwlTerminalLogo.toPngBytes(
    size: size,
    withBackground: withBackground,
    glowing: glowing,
  );
  final file = File(filePath);
  await file.parent.create(recursive: true);
  return file.writeAsBytes(bytes, flush: true);
}
