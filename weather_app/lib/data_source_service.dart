import 'dart:convert';
import 'package:http/http.dart' as http;
import 'weather_service.dart';
import 'data_source.dart';

Future<List<DataSource>> fetchDataSources() async {
  final baseUrl = await BackendConfig.getBaseUrl();
  final response = await http.get(Uri.parse('$baseUrl/data-sources/'));
  if (response.statusCode == 200) {
    final List data = jsonDecode(response.body);
    return data.map((json) => DataSource.fromJson(json)).toList();
  }
  throw Exception('Failed to load data sources');
}
