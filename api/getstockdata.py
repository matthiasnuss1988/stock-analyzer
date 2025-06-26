import json
from http.server import BaseHTTPRequestHandler
import yfinance as yf
from datetime import datetime, timedelta
import logging
import re
from urllib.parse import urlparse, parse_qs

# Konfiguriere Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def smart_symbol_search(user_input):
    """
    Intelligente Suche nach Yahoo Finance Symbol basierend auf verschiedenen Eingabeformaten:
    - Yahoo Symbol (AAPL, SAP.DE)
    - WKN (6 Ziffern: 716460)
    - ISIN (12 Zeichen: DE0007164600)
    - Firmenname (Apple, SAP)
    """
    user_input = user_input.strip()
    logger.info(f"Suche Symbol für: '{user_input}'")
    
    # 1. Prüfe ob es bereits ein gültiges Yahoo Symbol ist
    if is_valid_yahoo_symbol(user_input):
        logger.info(f"'{user_input}' ist bereits ein gültiges Yahoo Symbol")
        return user_input.upper()
    
    # 2. Erkenne Format und suche entsprechend
    symbol_format = detect_input_format(user_input)
    logger.info(f"Erkanntes Format: {symbol_format}")
    
    if symbol_format == "wkn":
        return search_by_wkn(user_input)
    elif symbol_format == "isin":
        return search_by_isin(user_input)
    elif symbol_format == "company_name":
        return search_by_company_name(user_input)
    else:
        # Fallback: Versuche generische Suche
        return search_generic(user_input)

def is_valid_yahoo_symbol(symbol):
    """Prüft ob ein Symbol bereits ein gültiges Yahoo Symbol ist."""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        # Wenn wir grundlegende Infos bekommen, ist es ein gültiges Symbol
        return 'symbol' in info or 'shortName' in info or 'longName' in info
    except:
        return False

def detect_input_format(user_input):
    """Erkennt das Format der Eingabe."""
    cleaned = re.sub(r'[^A-Z0-9]', '', user_input.upper())
    
    # WKN: Genau 6 Ziffern
    if re.match(r'^\d{6}$', cleaned):
        return "wkn"
    
    # ISIN: 12 Zeichen, beginnt mit 2 Buchstaben
    if re.match(r'^[A-Z]{2}[A-Z0-9]{10}$', cleaned):
        return "isin"
    
    # Enthält Buchstaben und ist länger als 6 Zeichen -> wahrscheinlich Firmenname
    if len(user_input) > 6 and re.search(r'[a-zA-Z]', user_input):
        return "company_name"
    
    return "unknown"

def search_by_wkn(wkn):
    """Sucht nach Yahoo Symbol basierend auf WKN."""
    # Deutsche WKNs haben oft .DE oder .F (Frankfurt) Endung
    possible_suffixes = ['.DE', '.F', '']
    
    # Erst versuchen mit bekannten deutschen Börsen-Suffixen
    for suffix in possible_suffixes:
        try:
            # Manche deutsche Aktien haben WKN als Teil des Symbols
            test_symbol = wkn + suffix
            if is_valid_yahoo_symbol(test_symbol):
                return test_symbol
        except:
            continue
    
    # Fallback: Suche über yfinance
    return search_generic(wkn)

def search_by_isin(isin):
    """Sucht nach Yahoo Symbol basierend auf ISIN."""
    # Deutsche ISINs beginnen mit DE
    if isin.startswith('DE'):
        # Versuche mit .DE Suffix
        test_symbols = [isin + '.DE', isin + '.F']
        for symbol in test_symbols:
            if is_valid_yahoo_symbol(symbol):
                return symbol
    
    # US ISINs beginnen mit US
    elif isin.startswith('US'):
        # US Aktien haben normalerweise kein Suffix
        if is_valid_yahoo_symbol(isin):
            return isin
    
    # Fallback: Suche über yfinance
    return search_generic(isin)

def search_by_company_name(company_name):
    """Sucht nach Yahoo Symbol basierend auf Firmenname."""
    return search_generic(company_name)

def search_generic(query):
    """Generische Suche über yfinance.search()."""
    try:
        logger.info(f"Führe yfinance.search() aus für: '{query}'")
        
        # Versuche yfinance search
        search_results = yf.search(query)
        
        if search_results and len(search_results) > 0:
            # Nimm das erste Ergebnis
            best_match = search_results.iloc[0]
            symbol = best_match['symbol']
            logger.info(f"yfinance.search() gefunden: {symbol} ({best_match.get('shortName', 'N/A')})")
            return symbol
        else:
            logger.warning(f"yfinance.search() fand keine Ergebnisse für '{query}'")
            # Fallback: Verwende die Eingabe direkt (vielleicht ist es trotzdem ein gültiges Symbol)
            return query.upper()
            
    except Exception as e:
        logger.error(f"Fehler bei yfinance.search(): {e}")
        # Fallback: Verwende die Eingabe direkt
        return query.upper()

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        """
        Die Hauptfunktion, die von Vercel Functions aufgerufen wird.
        Empfängt den HTTP-Request, ruft yfinance auf und gibt JSON zurück.
        """
        logger.info("Vercel Function 'getStockData' wurde aufgerufen.")
        
        # Parse URL und Query Parameter
        parsed_url = urlparse(self.path)
        query_params = parse_qs(parsed_url.query)
        
        # Symbol aus Query Parameter extrahieren
        symbol_param = query_params.get('symbol', [None])
        if not symbol_param or not symbol_param[0]:
            logger.warning("Fehler: 'symbol' Parameter fehlt im Request.")
            self._send_error_response(400, 'Symbol-Parameter fehlt. Bitte geben Sie ein Symbol, WKN, ISIN oder Firmenname ein.')
            return

        user_input = symbol_param[0]
        
        # 🎯 HIER IST DIE MAGIE: Intelligente Symbol-Suche!
        try:
            symbol = smart_symbol_search(user_input)
            logger.info(f"Konvertiert '{user_input}' zu Yahoo Symbol: '{symbol}'")
        except Exception as e:
            logger.error(f"Fehler bei Symbol-Suche: {e}")
            symbol = user_input.upper()  # Fallback

        try:
            ticker = yf.Ticker(symbol)

            # --- Aktuelle Daten abrufen ---
            info = ticker.info
            
            # Prüfe ob wir überhaupt Daten bekommen haben
            if not info or len(info) < 5:
                raise ValueError(f"Keine Daten für Symbol '{symbol}' gefunden. Möglicherweise ist '{user_input}' kein gültiges Symbol/WKN/ISIN.")
            
            # Prüfe, ob grundlegende Daten wie 'currentPrice' vorhanden sind
            if 'currentPrice' not in info or info.get('currentPrice') is None:
                # Versuche, den Kurs über eine kurze Historie zu bekommen, falls info leer ist
                current_data = ticker.history(period="1d", interval="1m")
                if not current_data.empty:
                    current_price = current_data['Close'].iloc[-1]
                    # Versuche vorherigen Schlusskurs vom Vortag zu bekommen
                    prev_day_data = ticker.history(period="2d", interval="1d")
                    previous_close = prev_day_data['Close'].iloc[-2] if len(prev_day_data) > 1 else current_price
                else:
                    logger.warning(f"Keine aktuellen Preisdaten in ticker.info oder history für {symbol}.")
                    # Wenn auch das nicht klappt, schlagen wir fehl
                    raise ValueError(f"Keine aktuellen Preisdaten für '{user_input}' gefunden.")
            else:
                current_price = info.get('currentPrice')
                previous_close = info.get('previousClose')

            long_name = info.get('longName', info.get('shortName', symbol))
            currency = info.get('currency', 'EUR') # Standard auf EUR für deutsche, USD für US-Aktien

            market_change = None
            market_change_percent = None
            if current_price is not None and previous_close is not None and previous_close != 0:
                market_change = current_price - previous_close
                market_change_percent = (market_change / previous_close) * 100

            # --- Historische Daten abrufen (für den Chart) ---
            # 'max' holt alle verfügbaren historischen Daten, '1d' für tägliche Intervalle
            hist = ticker.history(period="max", interval="1d")
            prices = []
            if not hist.empty:
                for index, row in hist.iterrows():
                    # Filtere potenziell leere Zeilen oder NaN-Werte heraus
                    if not (row[['Open', 'High', 'Low', 'Close']].isnull().any()):
                        prices.append({
                            "date": index.date().isoformat(), # Datum als ISO-String
                            "open": round(float(row['Open']), 2),
                            "high": round(float(row['High']), 2),
                            "low": round(float(row['Low']), 2),
                            "close": round(float(row['Close']), 2),
                            "volume": int(row['Volume'])
                        })

            # --- Dividenden abrufen (letzte 10 Jahre) ---
            dividends_df = ticker.dividends
            dividends = []
            if not dividends_df.empty:
                current_year = datetime.now().year
                annual_dividends = {}
                # Aggregiere Dividenden pro Jahr
                for index, value in dividends_df.items():
                    div_year = index.year
                    # Hier filtern wir für die letzten 10 vollen Jahre + das aktuelle Jahr
                    if div_year >= current_year - 10:
                        annual_dividends[div_year] = annual_dividends.get(div_year, 0) + value
                
                # Konvertiere das Dictionary in eine Liste von Objekten und sortiere absteigend nach Jahr
                for year, amount in annual_dividends.items():
                    dividends.append({"year": year, "amount": round(amount, 2)})
                dividends.sort(key=lambda x: x['year'], reverse=True) # Neuestes Jahr zuerst

            # --- Dividendenrendite berechnen ---
            dividend_yield = 0
            if current_price is not None and current_price > 0:
                # Versuche, die offizielle TTM (Trailing Twelve Months) Dividendenrendite von Yahoo zu bekommen
                official_yield = info.get('dividendYield') # Dies ist ein Prozentsatz (z.B. 0.02 für 2%)
                if official_yield is not None:
                    dividend_yield = official_yield * 100
                elif dividends:
                    # Fallback: Berechne aus der letzten vollen Jahresdividende
                    last_full_year_dividend = 0
                    for div in dividends:
                        if div['year'] == (current_year - 1) or (div['year'] == current_year and datetime.now().month >= 11):
                            last_full_year_dividend = div['amount']
                            break
                    if last_full_year_dividend > 0:
                        dividend_yield = (last_full_year_dividend / current_price) * 100

            # --- Zusätzliche Informationen für bessere Anzeige ---
            # Versuche WKN/ISIN aus den ticker.info zu extrahieren
            wkn = info.get('wkn', None)
            isin = info.get('isin', None)
            
            # Fallback: Versuche aus anderen Feldern
            if not wkn and not isin:
                # Manchmal stehen diese Infos in anderen Feldern
                security_info = info.get('quoteType', {})
                if isinstance(security_info, dict):
                    wkn = security_info.get('wkn', None)
                    isin = security_info.get('isin', None)
            
            # Sector und Industry für zusätzliche Info
            sector = info.get('sector', None)
            industry = info.get('industry', None)
            
            # Marktkapitalisierung
            market_cap = info.get('marketCap', None)
            
            response_data = {
                "symbol": symbol,
                "originalInput": user_input,  # Zeige was der User eingegeben hat
                "companyName": long_name,
                "wkn": wkn,
                "isin": isin,
                "sector": sector,
                "industry": industry,
                "marketCap": market_cap,
                "prices": prices,
                "currency": currency,
                "currentPrice": round(current_price, 2) if current_price is not None else None,
                "previousClose": round(previous_close, 2) if previous_close is not None else None,
                "marketChange": round(market_change, 2) if market_change is not None else None,
                "marketChangePercent": round(market_change_percent, 2) if market_change_percent is not None else None,
                "dividends": dividends,
                "dividendYield": round(dividend_yield, 2)
            }
            
            logger.info(f"Daten für {symbol} (eingegeben: {user_input}) erfolgreich abgerufen.")
            self._send_success_response(response_data)

        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Daten für {symbol} (eingegeben: {user_input}): {e}", exc_info=True)
            error_message = f"Fehler beim Abrufen der Daten für '{user_input}'. Bitte prüfen Sie die Eingabe (Symbol, WKN, ISIN oder Firmenname). Details: {str(e)}"
            
            if "No data found" in str(e) or "empty DataFrame" in str(e):
                 error_message = f"Für '{user_input}' wurden keine Daten gefunden. Bitte prüfen Sie die Eingabe."
            elif "Invalid input" in str(e):
                 error_message = f"Ungültige Eingabe '{user_input}'. Bitte verwenden Sie ein gültiges Symbol, WKN, ISIN oder Firmenname."

            self._send_error_response(500, error_message)
    
    def _send_success_response(self, data):
        """Sendet eine erfolgreiche JSON-Response."""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))
    
    def _send_error_response(self, status_code, error_message):
        """Sendet eine Fehler-Response."""
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        error_data = {'error': error_message}
        self.wfile.write(json.dumps(error_data).encode('utf-8'))

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
