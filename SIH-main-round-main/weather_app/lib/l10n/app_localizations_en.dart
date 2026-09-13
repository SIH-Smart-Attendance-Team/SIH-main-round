// ignore: unused_import
import 'package:intl/intl.dart' as intl;

import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for English (`en`).
class AppLocalizationsEn extends AppLocalizations {
  AppLocalizationsEn([String locale = 'en']) : super(locale);

  @override
  String get appTitle => 'WeatherGPT';

  @override
  String get subtitle => 'Your Intelligent Weather Assistant';

  @override
  String get welcomeBack => 'Welcome Back 👋';

  @override
  String get signInToContinue => 'Sign in to continue to WeatherGPT';

  @override
  String get createAccount => 'Create Account';

  @override
  String get joinWeatherGPT => 'Join WeatherGPT for personalized forecasts';

  @override
  String get name => 'Name';

  @override
  String get email => 'Email';

  @override
  String get password => 'Password';

  @override
  String get signIn => 'Sign In';

  @override
  String get signUp => 'Sign Up';

  @override
  String get dontHaveAccount => 'Don\'t have an account? Sign Up';

  @override
  String get alreadyHaveAccount => 'Already have an account? Sign In';

  @override
  String get pleaseEnterEmailAndPassword => 'Please enter email and password';

  @override
  String get currentConditions => 'Current Conditions';

  @override
  String get sevenDayForecast => '7-Day Forecast';

  @override
  String get climateEnvironmental => 'Climate & Environmental';

  @override
  String get agriculturalConditions => 'Agricultural Conditions';

  @override
  String get noClimateDataAvailable => 'No climate data available';

  @override
  String get noForecastData => 'No forecast data';

  @override
  String get temp => 'TEMP';

  @override
  String get humidity => 'HUMIDITY';

  @override
  String get wind => 'WIND';

  @override
  String get precip => 'PRECIP';

  @override
  String get pressure => 'PRESSURE';

  @override
  String feelsLike(Object temp) {
    return 'Feels like $temp°C';
  }

  @override
  String get persona => 'Persona';

  @override
  String get language => 'Language';

  @override
  String get farmer => 'Farmer';

  @override
  String get fisherman => 'Fisherman';

  @override
  String get urbanCommuter => 'Urban Commuter';

  @override
  String get searchCity => 'Search city...';

  @override
  String get typeCityToSearch => 'Type a city name to search';

  @override
  String get noResultsFound => 'No results found';

  @override
  String get couldNotReachBackend =>
      'Could not reach backend. Check your internet and settings.';

  @override
  String get settings => 'Settings';

  @override
  String get backendServer => 'Backend Server';

  @override
  String get backendUrlHint => 'http://192.168.1.100:8000';

  @override
  String get backendUrlDescription =>
      'Enter the URL of your WeatherGPT backend server.';

  @override
  String get save => 'Save';

  @override
  String get backendUrlSaved => 'Backend URL saved';

  @override
  String get pleaseEnterValidUrl =>
      'Please enter a valid URL (e.g. http://192.168.1.100:8000)';

  @override
  String current(Object url) {
    return 'Current: $url';
  }

  @override
  String get advisory => 'Advisory';

  @override
  String get textAdvisory => 'Text Advisory';

  @override
  String get holdToSpeak => 'Hold to speak';

  @override
  String get releaseToSend => 'Release to send';

  @override
  String get typeMessage => 'Type a message...';

  @override
  String get send => 'Send';

  @override
  String get weatherQuestion => 'Weather Question';

  @override
  String personaLabel(Object lang, Object persona) {
    return 'Persona: $persona | Language: $lang';
  }

  @override
  String get cancel => 'Cancel';

  @override
  String get sendQuestion => 'Send';

  @override
  String get noActiveWeatherAlerts => 'No Active Weather Alerts';

  @override
  String get currentConditionsNormal =>
      'Current conditions are within normal range.';

  @override
  String get marineConditions => 'Marine Conditions';

  @override
  String get soilTemp => 'Soil Temp';

  @override
  String get soilMoisture => 'Soil Moisture';

  @override
  String get leafWetness => 'Leaf Wetness';

  @override
  String get waveHeight => 'Wave Height';

  @override
  String get seaTemp => 'Sea Temp';

  @override
  String get windGusts => 'Wind Gusts';
}
