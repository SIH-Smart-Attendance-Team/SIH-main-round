import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'weather_service.dart';

class AuthService {
  static const String _tokenKey = 'auth_token';
  static const String _userKey = 'auth_user';
  static const String _baseUrlKey = 'backend_url';

  String? _token;
  String _baseUrl = kBackendBaseUrl;

  bool get isAuthenticated => _token != null;
  String? get token => _token;
  String get baseUrl => _baseUrl;

  Future<void> init() async {
    final prefs = await SharedPreferences.getInstance();
    _token = prefs.getString(_tokenKey);
    _baseUrl = prefs.getString(_baseUrlKey) ?? kBackendBaseUrl;
  }

  Future<void> saveToken(String token, Map<String, dynamic> user) async {
    _token = token;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_tokenKey, token);
    await prefs.setString(_userKey, jsonEncode(user));
  }

  Future<void> logout() async {
    _token = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_tokenKey);
    await prefs.remove(_userKey);
  }

  Future<Map<String, dynamic>> signup({
    required String email,
    required String password,
    String? name,
  }) async {
    final res = await http
        .post(
           Uri.parse('$_baseUrl/api/v1/auth/signup'),
          body: {
            'email': email,
            'password': password,
            ...?name != null ? {'name': name} : null,
          },
        )
        .timeout(const Duration(seconds: 15));

    if (res.statusCode != 200) {
      final data = jsonDecode(res.body);
      throw AuthException(data['detail'] ?? 'Signup failed');
    }
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    await saveToken(data['access_token'], {'email': email, 'name': name ?? ''});
    return data;
  }

  Future<Map<String, dynamic>> login({
    required String email,
    required String password,
  }) async {
    final res = await http
        .post(
           Uri.parse('$_baseUrl/api/v1/auth/login'),
          body: {
            'email': email,
            'password': password,
          },
        )
        .timeout(const Duration(seconds: 15));

    if (res.statusCode != 200) {
      final data = jsonDecode(res.body);
      throw AuthException(data['detail'] ?? 'Login failed');
    }
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    final userRes = await http.get(
      Uri.parse('$_baseUrl/api/v1/auth/me'),
      headers: {'Authorization': 'Bearer ${data['access_token']}'},
    );
    Map<String, dynamic> user = {};
    if (userRes.statusCode == 200) {
      user = jsonDecode(userRes.body) as Map<String, dynamic>;
    }
    await saveToken(data['access_token'], user);
    return data;
  }
}

class AuthException implements Exception {
  final String message;
  AuthException(this.message);
  @override
  String toString() => 'AuthException: $message';
}
