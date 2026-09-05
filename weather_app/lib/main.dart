import 'package:flutter/material.dart';
import 'auth_service.dart';
import 'auth_page.dart';
import 'offline_service.dart';
import 'weather_dashboard_pg.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await OfflineServices.instance.init();
  final auth = AuthService();
  await auth.init();
  runApp(MyApp(isAuthenticated: auth.isAuthenticated));
}

class MyApp extends StatelessWidget {
  final bool isAuthenticated;

  const MyApp({super.key, required this.isAuthenticated});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'WeatherGPT',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.deepPurple),
        useMaterial3: true,
      ),
      home: isAuthenticated ? const WeatherDashboardPage() : const AuthPage(),
    );
  }
}
