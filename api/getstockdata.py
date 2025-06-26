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
        hist = ticker.history(period="1d")
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
            return query.upper()
            
    except Exception as e:
        logger.error(f"Fehler bei yfinance.search(): {e}")
        return query.upper()

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Hauptfunktion für Vercel."""
        logger.info("Vercel Function aufgerufen")
        
        # CORS Headers setzen
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        
        try:
            # Parse URL
            parsed_url = urlparse(self.path)
            query_params = parse_qs(parsed_url.query)
            
            # Symbol Parameter
            symbol_param = query_params.get('symbol', [None])
            if not symbol_param or not symbol_param[0]:
                self.end_headers()
                self.wfile.write(json.dumps({
                    'error': 'Symbol-Parameter fehlt. Bitte geben Sie ein Symbol, WKN, ISIN oder Firmenname ein.'
                }).encode('utf-8'))
                return

            user_input = symbol_param[0]
            
            # Smart Search
            try:
                symbol = smart_symbol_search(user_input)
                logger.info(f"Konvertiert '{user_input}' zu '{symbol}'")
            except Exception as e:
                logger.error(f"Fehler bei Symbol-Suche: {e}")
                symbol = user_input.upper()

            # Yahoo Finance Daten abrufen
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            # Basis-Validierung
            if not info or len(info) < 3:
                self.end_headers()
                self.wfile.write(json.dumps({
                    'error': f"Keine Daten für '{user_input}' gefunden. Bitte prüfen Sie die Eingabe."
                }).encode('utf-8'))
                return
            
            # Aktuelle Preise
            current_price = info.get('currentPrice')
            previous_close = info.get('previousClose')
            
            # Fallback für Preise
            if not current_price:
                try:
                    current_data = ticker.history(period="2d")
                    if not current_data.empty:
                        current_price = current_data['Close'].iloc[-1]
                        if len(current_data) > 1:
                            previous_close = current_data['Close'].iloc[-2]
                except:
                    pass
            
            if not current_price:
                self.end_headers()
                self.wfile.write(json.dumps({
                    'error': f"Keine aktuellen Preisdaten für '{user_input}' gefunden."
                }).encode('utf-8'))
                return
            
            # Weitere Daten
            long_name = info.get('longName', info.get('shortName', symbol))
            currency = info.get('currency', 'EUR')
            
            # Marktänderung
            market_change = None
            market_change_percent = None
            if current_price and previous_close and previous_close != 0:
                market_change = current_price - previous_close
                market_change_percent = (market_change / previous_close) * 100
            
            # Historische Daten
            hist = ticker.history(period="max", interval="1d")
            prices = []
            if not hist.empty:
                for index, row in hist.iterrows():
                    if not (row[['Open', 'High', 'Low', 'Close']].isnull().any()):
                        prices.append({
                            "date": index.date().isoformat(),
                            "open": round(float(row['Open']), 2),
                            "high": round(float(row['High']), 2),
                            "low": round(float(row['Low']), 2),
                            "close": round(float(row['Close']), 2),
                            "volume": int(row['Volume'])
                        })
            
            # Dividenden
            dividends_df = ticker.dividends
            dividends = []
            if not dividends_df.empty:
                current_year = datetime.now().year
                annual_dividends = {}
                for index, value in dividends_df.items():
                    div_year = index.year
                    if div_year >= current_year - 10:
                        annual_dividends[div_year] = annual_dividends.get(div_year, 0) + value
                
                for year, amount in annual_dividends.items():
                    dividends.append({"year": year, "amount": round(amount, 2)})
                dividends.sort(key=lambda x: x['year'], reverse=True)
            
            # Dividendenrendite
            dividend_yield = 0
            official_yield = info.get('dividendYield')
            if official_yield:
                dividend_yield = official_yield * 100
            elif dividends and current_price:
                last_div = dividends[0]['amount'] if dividends else 0
                if last_div > 0:
                    dividend_yield = (last_div / current_price) * 100
            
            # Zusätzliche Infos
            wkn = info.get('wkn')
            isin = info.get('isin')
            sector = info.get('sector')
            
            # Response
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
                "dividendYield": round(dividend_yield, 2)
            }
            
            self.end_headers()
            self.wfile.write(json.dumps(response_data).encode('utf-8'))
            logger.info(f"Erfolgreich: {symbol} für '{user_input}'")
            
        except Exception as e:
            logger.error(f"Fehler in handler: {e}", exc_info=True)
            self.end_headers()
            self.wfile.write(json.dumps({
                'error': f'Serverfehler: {str(e)}'
            }).encode('utf-8'))
    
    def do_OPTIONS(self):
        """CORS Preflight."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
