import 'package:flutter_test/flutter_test.dart';

import 'package:weather_app/main.dart';

void main() {
  testWidgets('WeatherGPT app shows auth page when not authenticated',
      (WidgetTester tester) async {
    // Build our app and trigger a frame.
    await tester.pumpWidget(const MyApp(isAuthenticated: false));

    // Verify the auth UI renders correctly
    expect(find.text('WeatherGPT'), findsOneWidget);
    expect(find.text('Sign In'), findsOneWidget);
    expect(find.text('Email'), findsOneWidget);
    expect(find.text('Password'), findsOneWidget);
  });
}