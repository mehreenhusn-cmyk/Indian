"""Part 27: static checks for the central route map (NOT RUN by owner rule; Dart is not compiled here)."""
import os, re, unittest
LIB = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'lib')
def rd(*p):
    return open(os.path.join(LIB, *p), encoding='utf-8').read()

class RouteMap(unittest.TestCase):
    def test_numbers_match_main_screens_list(self):
        src = rd('navigation', 'app_routes.dart')
        got = dict(re.findall(r'AppRoute\.(\w+): (\d),', src))
        self.assertEqual(got, {'dashboard': '0', 'market': '1', 'positions': '2', 'signals': '3',
                               'dualBot': '4', 'ai': '5', 'more': '6', 'brain': '7'})
    def test_no_number_goToTab_left(self):
        for f in (('screens', 'more_screen.dart'), ('widgets', 'dashboard_cockpit.dart')):
            self.assertIsNone(re.search(r'goToTab\(\d', rd(*f)), f)
        self.assertIsNone(re.search(r'goToTab\(\d', rd('providers', 'app_provider.dart').split('Part 27')[1]))
    def test_main_and_bar_use_map(self):
        self.assertIn('AppRoutes.swipeScreens', rd('main.dart'))
        self.assertIn('AppRoutes.barScreens', rd('widgets', 'bottom_nav_bar.dart'))
    def test_pure_dart(self):
        self.assertNotIn('import ', rd('navigation', 'app_routes.dart'))
if __name__ == '__main__':
    unittest.main()
