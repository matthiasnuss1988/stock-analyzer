import json
from http.server import BaseHTTPRequestHandler
import yfinance as yf
from datetime import datetime, timedelta
import logging
import re
from urllib.parse import urlparse, parse_qs
import traceback # NEU: Für detaillierte Fehlermeldungen

# Konfiguriere Logging
# Setze Level auf DEBUG, um alle logger.debug Meldungen zu sehen
logging.basicConfig(level=logging.DEBUG) # ANGEPASST: DEBUG für mehr Infos
logger = logging.getLogger(__name__)

# Bekannte Mappings als Fallback (die wichtigsten deutschen Aktien)
KNOWN_MAPPINGS = {
    # WKNs
    '716460': 'SAP.DE',
    '840400': 'ALV.DE',
    '723610': 'SIE.DE',
    '519000': 'BMW.DE',
    'BASF11': 'BAS.DE',
    '515100': 'MBG.DE',
    '766403': 'VOW3.DE',
    '850471': 'ADS.DE',
    # ISINs
    'DE0007164600': 'SAP.DE',
    'DE0008404005': 'ALV.DE',
    'DE0007236101': 'SIE.DE',
    'DE0005190003': 'BMW.DE',
    'DE000BASF111': 'BAS.DE',
    'DE0005151005': 'MBG.DE',
    'DE0007664039': 'VOW3.DE',
    'DE000A1EWWW0': 'ADS.DE',
    # US Stocks
    'US0378331005': 'AAPL',
    'US5949181045': 'MSFT'
}

def smart_symbol_search(user_input):
    """Intelligente Suche mit verbesserter Fehlerbehandlung."""
    user_input = user_input.strip()
    logger.info(f"Suche Symbol für: '{user_input}'")

    # 1. Direkter Test
    if is_valid_yahoo_symbol(user_input):
        logger.info(f"'{user_input}' ist bereits ein gültiges Yahoo Symbol")
        return user_input.upper()

    # 2. Bekannte Mappings prüfen
    cleaned = re.sub(r'[^A-Z0-9]', '', user_input.upper())
    if cleaned in KNOWN_MAPPINGS:
        logger.info(f"Bekannte Mapping gefunden: {cleaned} -> {KNOWN_MAPPINGS[cleaned]}")
        return KNOWN_MAPPINGS[cleaned]

    # 3. Format-basierte Suche
    symbol_format = detect_input_format(user_input)
    logger.info(f"Erkanntes Format: {symbol_format}")

    if symbol_format == "wkn":
        return search_by_wkn(user_input)
    elif symbol_format == "isin":
        return search_by_isin(user_input)
    elif symbol_format == "company_name":
        return search_by_company_name(user_input)
    else:
        return search_generic(user_input)

def is_valid_yahoo_symbol(symbol):
    """Prüft Yahoo Symbol mit Timeout."""
    try:
        ticker = yf.Ticker(symbol)
        # Kurzer Test mit minimalen Daten
        hist = ticker.history(period="1d", interval="1d") # Explizites Interval
        return not hist.empty
    except Exception as e:
        logger.debug(f"Symbol '{symbol}' ist nicht gültig: {e}")
        return False

def detect_input_format(user_input):
    """Erkennt das Eingabeformat."""
    cleaned = re.sub(r'[^A-Z0-9]', '', user_input.upper())

    if re.match(r'^\d{6}$', cleaned):
        return "wkn"
    elif re.match(r'^[A-Z]{2}[A-Z0-9]{10}$', cleaned):
        return "isin"
    elif len(user_input) > 6 and re.search(r'[a-zA-Z]', user_input):
        return "company_name"

    return "unknown"

def search_by_wkn(wkn):
    """Suche nach WKN mit deutschen Suffixen."""
    for suffix in ['.DE', '.F']:
        test_symbol = wkn + suffix
        if is_valid_yahoo_symbol(test_symbol):
            return test_symbol
    return search_generic(wkn)

def search_by_isin(isin):
    """Suche nach ISIN."""
    if isin.startswith('DE'):
        for suffix in ['.DE', '.F']:
            test_symbol = isin + suffix
            if is_valid_yahoo_symbol(test_symbol):
                return test_symbol
    elif isin.startswith('US'):
        if is_valid_yahoo_symbol(isin):
            return isin
    return search_generic(isin)

def search_by_company_name(company_name):
    """Suche nach Firmenname."""
    return search_generic(company_name)

def search_generic(query):
    """Generische Suche mit robuster Fehlerbehandlung."""
    try:
        logger.info(f"Führe yfinance.search() aus für: '{query}'")

        # Versuche yfinance search mit Timeout
        search_results = yf.search(query, max_results=3)

        if search_results is not None and not search_results.empty and len(search_results) > 0:
            best_match = search_results.iloc[0]
            symbol = best_match['symbol']
            name = best_match.get('shortName', best_match.get('longName', 'N/A'))
            logger.info(f"yfinance.search() gefunden: {symbol} ({name})")
            return symbol
        else:
            logger.warning(f"yfinance.search() fand keine Ergebnisse für '{query}'")
            # Rückgabe des Original-Queries, wenn keine direkten Ergebnisse
            return query.upper()

    except Exception as e:
        logger.error(f"Fehler bei yfinance.search(): {e}")
        # Rückgabe des Original-Queries bei Fehler, damit es weiterverarbeitet wird
        return query.upper()

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Hauptfunktion für Vercel."""
        logger.info("Vercel Function aufgerufen")

        # Setze CORS Header am Anfang, aber sende sie erst am Ende
        # Der 200 OK wird im Try-Block gesendet
        # Der 500 ERROR wird im Except-Block gesendet
        common_headers = {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type'
        }

        try:
            # Parse URL
            parsed_url = urlparse(self.path)
            query_params = parse_qs(parsed_url.query)

            # Symbol Parameter
            symbol_param = query_params.get('symbol', [None])

            # --- DEBUGGING-AUSGABE 1: Empfangene URL-Parameter ---
            logger.debug(f"Empfangene URL-Parameter: {query_params}")
            debug_info_params = {"received_url_params": query_params}

            if not symbol_param or not symbol_param[0]:
                self.send_response(400) # Bad Request
                for header, value in common_headers.items():
                    self.send_header(header, value)
                self.end_headers()
                self.wfile.write(json.dumps({
                    'error': 'Symbol-Parameter fehlt. Bitte geben Sie ein Symbol, WKN, ISIN oder Firmenname ein.',
                    'debug_info': debug_info_params # Füge Debug-Info auch hier hinzu
                }).encode('utf-8'))
                return

            user_input = symbol_param[0]

            # Smart Search
            try:
                symbol = smart_symbol_search(user_input)
                logger.info(f"Konvertiert '{user_input}' zu '{symbol}'")
                # --- DEBUGGING-AUSGABE 2: Ergebnis der Symbol-Suche ---
                debug_info_params["resolved_symbol"] = symbol
            except Exception as e:
                logger.error(f"Fehler bei Symbol-Suche: {e}")
                symbol = user_input.upper()
                debug_info_params["resolved_symbol_error"] = str(e)


            # Yahoo Finance Daten abrufen
            ticker = yf.Ticker(symbol)
            info = ticker.info

            # --- DEBUGGING-AUSGABE 3: Erste Daten von YFinance (ticker.info) ---
            # Prüfe, ob 'info' Daten enthält, bevor du es loggst oder hinzufügst
            if info:
                logger.debug(f"Erste Ticker-Info für '{symbol}': {info.get('shortName', 'N/A')}, Currency: {info.get('currency', 'N/A')}")
                # Füge einen Teil der Info für Debugging hinzu (nicht alles, da es sehr groß sein kann)
                debug_info_params["yfinance_initial_info"] = {
                    "symbol": symbol,
                    "shortName": info.get('shortName'),
                    "currency": info.get('currency'),
                    "currentPrice_from_info": info.get('currentPrice')
                }
            else:
                 logger.debug(f"DEBUG: Ticker info for '{symbol}' returned empty.")
                 debug_info_params["yfinance_initial_info"] = "Empty or invalid info received."


            # Basis-Validierung
            if not info or len(info) < 3: # Hier könnte man prüfen, ob wichtige Keys fehlen
                self.send_response(404) # Not Found
                for header, value in common_headers.items():
                    self.send_header(header, value)
                self.end_headers()
                self.wfile.write(json.dumps({
                    'error': f"Keine ausreichenden Daten für '{user_input}' gefunden. Bitte prüfen Sie die Eingabe oder das Symbol.",
                    'debug_info': debug_info_params
                }).encode('utf-8'))
                return

            # ... (Der Rest deines Codes zum Verarbeiten der Daten) ...
            # Deine Logik für current_price, previous_close, long_name, etc. ist hier

            # Füge die Debug-Informationen zur finalen Antwort hinzu
            response_data = {
                "symbol": symbol,
                "originalInput": user_input,
                "companyName": long_name,
                "wkn": wkn,
                "isin": isin,
                "sector": sector,
                "prices": prices,
                "currency": currency,
                "currentPrice": round(current_price, 2) if current_price else None,
                "previousClose": round(previous_close, 2) if previous_close else None,
                "marketChange": round(market_change, 2) if market_change else None,
                "marketChangePercent": round(market_change_percent, 2) if market_change_percent else None,
                "dividends": dividends,
                "dividendYield": round(dividend_yield, 2),
                "debug_info": debug_info_params # Füge die Debug-Infos hier hinzu
            }

            self.send_response(200) # OK
            for header, value in common_headers.items():
                self.send_header(header, value)
            self.end_headers()
            self.wfile.write(json.dumps(response_data).encode('utf-8'))
            logger.info(f"Erfolgreich: {symbol} für '{user_input}'")

        except Exception as e:
            error_type = type(e).__name__
            error_message = str(e)
            error_traceback = traceback.format_exc() # Voller Stack-Trace

            logger.error(f"Schwerwiegender Fehler in handler: {error_type} - {error_message}", exc_info=True)

            self.send_response(500) # Internal Server Error
            for header, value in common_headers.items():
                self.send_header(header, value)
            self.end_headers()

            self.wfile.write(json.dumps({
                'error': f'Serverfehler: {error_message}',
                'error_type': error_type,
                'details': error_traceback, # ACHTUNG: Nur für Debugging, in Produktion entfernen!
                'debug_info_at_error': debug_info_params.get("resolved_symbol", "N/A") # Zeigt, bis wohin wir gekommen sind
            }).encode('utf-8'))
    
    def do_OPTIONS(self):
        """CORS Preflight."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

