import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/intl.dart' as intl;

import 'app_localizations_en.dart';

// ignore_for_file: type=lint

/// Callers can lookup localized strings with an instance of AppLocalizations
/// returned by `AppLocalizations.of(context)`.
///
/// Applications need to include `AppLocalizations.delegate()` in their app's
/// `localizationDelegates` list, and the locales they support in the app's
/// `supportedLocales` list. For example:
///
/// ```dart
/// import 'l10n/app_localizations.dart';
///
/// return MaterialApp(
///   localizationsDelegates: AppLocalizations.localizationsDelegates,
///   supportedLocales: AppLocalizations.supportedLocales,
///   home: MyApplicationHome(),
/// );
/// ```
///
/// ## Update pubspec.yaml
///
/// Please make sure to update your pubspec.yaml to include the following
/// packages:
///
/// ```yaml
/// dependencies:
///   # Internationalization support.
///   flutter_localizations:
///     sdk: flutter
///   intl: any # Use the pinned version from flutter_localizations
///
///   # Rest of dependencies
/// ```
///
/// ## iOS Applications
///
/// iOS applications define key application metadata, including supported
/// locales, in an Info.plist file that is built into the application bundle.
/// To configure the locales supported by your app, you’ll need to edit this
/// file.
///
/// First, open your project’s ios/Runner.xcworkspace Xcode workspace file.
/// Then, in the Project Navigator, open the Info.plist file under the Runner
/// project’s Runner folder.
///
/// Next, select the Information Property List item, select Add Item from the
/// Editor menu, then select Localizations from the pop-up menu.
///
/// Select and expand the newly-created Localizations item then, for each
/// locale your application supports, add a new item and select the locale
/// you wish to add from the pop-up menu in the Value field. This list should
/// be consistent with the languages listed in the AppLocalizations.supportedLocales
/// property.
abstract class AppLocalizations {
  AppLocalizations(String locale)
    : localeName = intl.Intl.canonicalizedLocale(locale.toString());

  final String localeName;

  static AppLocalizations? of(BuildContext context) {
    return Localizations.of<AppLocalizations>(context, AppLocalizations);
  }

  static const LocalizationsDelegate<AppLocalizations> delegate =
      _AppLocalizationsDelegate();

  /// A list of this localizations delegate along with the default localizations
  /// delegates.
  ///
  /// Returns a list of localizations delegates containing this delegate along with
  /// GlobalMaterialLocalizations.delegate, GlobalCupertinoLocalizations.delegate,
  /// and GlobalWidgetsLocalizations.delegate.
  ///
  /// Additional delegates can be added by appending to this list in
  /// MaterialApp. This list does not have to be used at all if a custom list
  /// of delegates is preferred or required.
  static const List<LocalizationsDelegate<dynamic>> localizationsDelegates =
      <LocalizationsDelegate<dynamic>>[
        delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
      ];

  /// A list of this localizations delegate's supported locales.
  static const List<Locale> supportedLocales = <Locale>[Locale('en')];

  /// No description provided for @appTitle.
  ///
  /// In en, this message translates to:
  /// **'WeatherGPT'**
  String get appTitle;

  /// No description provided for @subtitle.
  ///
  /// In en, this message translates to:
  /// **'Your Intelligent Weather Assistant'**
  String get subtitle;

  /// No description provided for @welcomeBack.
  ///
  /// In en, this message translates to:
  /// **'Welcome Back 👋'**
  String get welcomeBack;

  /// No description provided for @signInToContinue.
  ///
  /// In en, this message translates to:
  /// **'Sign in to continue to WeatherGPT'**
  String get signInToContinue;

  /// No description provided for @createAccount.
  ///
  /// In en, this message translates to:
  /// **'Create Account'**
  String get createAccount;

  /// No description provided for @joinWeatherGPT.
  ///
  /// In en, this message translates to:
  /// **'Join WeatherGPT for personalized forecasts'**
  String get joinWeatherGPT;

  /// No description provided for @name.
  ///
  /// In en, this message translates to:
  /// **'Name'**
  String get name;

  /// No description provided for @email.
  ///
  /// In en, this message translates to:
  /// **'Email'**
  String get email;

  /// No description provided for @password.
  ///
  /// In en, this message translates to:
  /// **'Password'**
  String get password;

  /// No description provided for @signIn.
  ///
  /// In en, this message translates to:
  /// **'Sign In'**
  String get signIn;

  /// No description provided for @signUp.
  ///
  /// In en, this message translates to:
  /// **'Sign Up'**
  String get signUp;

  /// No description provided for @dontHaveAccount.
  ///
  /// In en, this message translates to:
  /// **'Don\'t have an account? Sign Up'**
  String get dontHaveAccount;

  /// No description provided for @alreadyHaveAccount.
  ///
  /// In en, this message translates to:
  /// **'Already have an account? Sign In'**
  String get alreadyHaveAccount;

  /// No description provided for @pleaseEnterEmailAndPassword.
  ///
  /// In en, this message translates to:
  /// **'Please enter email and password'**
  String get pleaseEnterEmailAndPassword;

  /// No description provided for @currentConditions.
  ///
  /// In en, this message translates to:
  /// **'Current Conditions'**
  String get currentConditions;

  /// No description provided for @sevenDayForecast.
  ///
  /// In en, this message translates to:
  /// **'7-Day Forecast'**
  String get sevenDayForecast;

  /// No description provided for @climateEnvironmental.
  ///
  /// In en, this message translates to:
  /// **'Climate & Environmental'**
  String get climateEnvironmental;

  /// No description provided for @agriculturalConditions.
  ///
  /// In en, this message translates to:
  /// **'Agricultural Conditions'**
  String get agriculturalConditions;

  /// No description provided for @noClimateDataAvailable.
  ///
  /// In en, this message translates to:
  /// **'No climate data available'**
  String get noClimateDataAvailable;

  /// No description provided for @noForecastData.
  ///
  /// In en, this message translates to:
  /// **'No forecast data'**
  String get noForecastData;

  /// No description provided for @temp.
  ///
  /// In en, this message translates to:
  /// **'TEMP'**
  String get temp;

  /// No description provided for @humidity.
  ///
  /// In en, this message translates to:
  /// **'HUMIDITY'**
  String get humidity;

  /// No description provided for @wind.
  ///
  /// In en, this message translates to:
  /// **'WIND'**
  String get wind;

  /// No description provided for @precip.
  ///
  /// In en, this message translates to:
  /// **'PRECIP'**
  String get precip;

  /// No description provided for @pressure.
  ///
  /// In en, this message translates to:
  /// **'PRESSURE'**
  String get pressure;

  /// No description provided for @feelsLike.
  ///
  /// In en, this message translates to:
  /// **'Feels like {temp}°C'**
  String feelsLike(Object temp);

  /// No description provided for @persona.
  ///
  /// In en, this message translates to:
  /// **'Persona'**
  String get persona;

  /// No description provided for @language.
  ///
  /// In en, this message translates to:
  /// **'Language'**
  String get language;

  /// No description provided for @farmer.
  ///
  /// In en, this message translates to:
  /// **'Farmer'**
  String get farmer;

  /// No description provided for @fisherman.
  ///
  /// In en, this message translates to:
  /// **'Fisherman'**
  String get fisherman;

  /// No description provided for @urbanCommuter.
  ///
  /// In en, this message translates to:
  /// **'Urban Commuter'**
  String get urbanCommuter;

  /// No description provided for @searchCity.
  ///
  /// In en, this message translates to:
  /// **'Search city...'**
  String get searchCity;

  /// No description provided for @typeCityToSearch.
  ///
  /// In en, this message translates to:
  /// **'Type a city name to search'**
  String get typeCityToSearch;

  /// No description provided for @noResultsFound.
  ///
  /// In en, this message translates to:
  /// **'No results found'**
  String get noResultsFound;

  /// No description provided for @couldNotReachBackend.
  ///
  /// In en, this message translates to:
  /// **'Could not reach backend. Check your internet and settings.'**
  String get couldNotReachBackend;

  /// No description provided for @settings.
  ///
  /// In en, this message translates to:
  /// **'Settings'**
  String get settings;

  /// No description provided for @backendServer.
  ///
  /// In en, this message translates to:
  /// **'Backend Server'**
  String get backendServer;

  /// No description provided for @backendUrlHint.
  ///
  /// In en, this message translates to:
  /// **'http://192.168.1.100:8000'**
  String get backendUrlHint;

  /// No description provided for @backendUrlDescription.
  ///
  /// In en, this message translates to:
  /// **'Enter the URL of your WeatherGPT backend server.'**
  String get backendUrlDescription;

  /// No description provided for @save.
  ///
  /// In en, this message translates to:
  /// **'Save'**
  String get save;

  /// No description provided for @backendUrlSaved.
  ///
  /// In en, this message translates to:
  /// **'Backend URL saved'**
  String get backendUrlSaved;

  /// No description provided for @pleaseEnterValidUrl.
  ///
  /// In en, this message translates to:
  /// **'Please enter a valid URL (e.g. http://192.168.1.100:8000)'**
  String get pleaseEnterValidUrl;

  /// No description provided for @current.
  ///
  /// In en, this message translates to:
  /// **'Current: {url}'**
  String current(Object url);

  /// No description provided for @advisory.
  ///
  /// In en, this message translates to:
  /// **'Advisory'**
  String get advisory;

  /// No description provided for @textAdvisory.
  ///
  /// In en, this message translates to:
  /// **'Text Advisory'**
  String get textAdvisory;

  /// No description provided for @holdToSpeak.
  ///
  /// In en, this message translates to:
  /// **'Hold to speak'**
  String get holdToSpeak;

  /// No description provided for @releaseToSend.
  ///
  /// In en, this message translates to:
  /// **'Release to send'**
  String get releaseToSend;

  /// No description provided for @typeMessage.
  ///
  /// In en, this message translates to:
  /// **'Type a message...'**
  String get typeMessage;

  /// No description provided for @send.
  ///
  /// In en, this message translates to:
  /// **'Send'**
  String get send;

  /// No description provided for @weatherQuestion.
  ///
  /// In en, this message translates to:
  /// **'Weather Question'**
  String get weatherQuestion;

  /// No description provided for @personaLabel.
  ///
  /// In en, this message translates to:
  /// **'Persona: {persona} | Language: {lang}'**
  String personaLabel(Object lang, Object persona);

  /// No description provided for @cancel.
  ///
  /// In en, this message translates to:
  /// **'Cancel'**
  String get cancel;

  /// No description provided for @sendQuestion.
  ///
  /// In en, this message translates to:
  /// **'Send'**
  String get sendQuestion;

  /// No description provided for @noActiveWeatherAlerts.
  ///
  /// In en, this message translates to:
  /// **'No Active Weather Alerts'**
  String get noActiveWeatherAlerts;

  /// No description provided for @currentConditionsNormal.
  ///
  /// In en, this message translates to:
  /// **'Current conditions are within normal range.'**
  String get currentConditionsNormal;

  /// No description provided for @marineConditions.
  ///
  /// In en, this message translates to:
  /// **'Marine Conditions'**
  String get marineConditions;

  /// No description provided for @soilTemp.
  ///
  /// In en, this message translates to:
  /// **'Soil Temp'**
  String get soilTemp;

  /// No description provided for @soilMoisture.
  ///
  /// In en, this message translates to:
  /// **'Soil Moisture'**
  String get soilMoisture;

  /// No description provided for @leafWetness.
  ///
  /// In en, this message translates to:
  /// **'Leaf Wetness'**
  String get leafWetness;

  /// No description provided for @waveHeight.
  ///
  /// In en, this message translates to:
  /// **'Wave Height'**
  String get waveHeight;

  /// No description provided for @seaTemp.
  ///
  /// In en, this message translates to:
  /// **'Sea Temp'**
  String get seaTemp;

  /// No description provided for @windGusts.
  ///
  /// In en, this message translates to:
  /// **'Wind Gusts'**
  String get windGusts;
}

class _AppLocalizationsDelegate
    extends LocalizationsDelegate<AppLocalizations> {
  const _AppLocalizationsDelegate();

  @override
  Future<AppLocalizations> load(Locale locale) {
    return SynchronousFuture<AppLocalizations>(lookupAppLocalizations(locale));
  }

  @override
  bool isSupported(Locale locale) =>
      <String>['en'].contains(locale.languageCode);

  @override
  bool shouldReload(_AppLocalizationsDelegate old) => false;
}

AppLocalizations lookupAppLocalizations(Locale locale) {
  // Lookup logic when only language code is specified.
  switch (locale.languageCode) {
    case 'en':
      return AppLocalizationsEn();
  }

  throw FlutterError(
    'AppLocalizations.delegate failed to load unsupported locale "$locale". This is likely '
    'an issue with the localizations generation tool. Please file an issue '
    'on GitHub with a reproducible sample app and the gen-l10n configuration '
    'that was used.',
  );
}
