import json
from http.server import BaseHTTPRequestHandler
import yfinance as yf
from datetime import datetime, timedelta
import logging
import re

# Konfiguriere Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mappings für WKN/ISIN zu Yahoo-Symbolen (erweitert)
symbol_mappings = {
    '716460': 'SAP.DE',
    'DE0007164600': 'SAP.DE',
    '840400': 'ALV.DE',
    'DE0008404005': 'ALV.DE',
    '723610': 'SIE.DE',
    'DE0007236101': 'SIE.DE',
    '519000': 'BMW.DE',
    'DE0005190003': 'BMW.DE',
    'BASF11': 'BAS.DE',
    'DE000BASF111': 'BAS.DE',
    '515100': 'MBG.DE', # Mercedes-Benz
    'DE0005151005': 'MBG.DE',
    '766403': 'VOW3.DE', # Volkswagen
    'DE0007664039': 'VOW3.DE',
    '850471': 'ADS.DE', # Adidas
    'DE000A1EWWW0': 'ADS.DE',
    
    # Gängige US-Aktien
    'AAPL': 'AAPL',
    'MSFT': 'MSFT',
    'GOOGL': 'GOOGL',
    'AMZN': 'AMZN',
    'TSLA': 'TSLA',
    'NVDA': 'NVDA',

    # Beispiel für NASDAQ Symbole falls direkt eingegeben
    'NDX': '^NDX', # Nasdaq 100 Index
    'DJI': '^DJI', # Dow Jones Industrial Average
    'GDAXI': '^GDAXI', # DAX Index
}

def convert_to_yahoo_symbol(input_symbol):
    """Konvertiert eine Eingabe (WKN, ISIN oder Symbol) in ein Yahoo Finance Symbol."""
    cleaned = re.sub(r'[^A-Z0-9]', '', input_symbol.upper())
    # Prüfe zuerst in den Mappings, dann versuche es direkt (für gängige Yahoo-Symbole)
    return symbol_mappings.get(cleaned, input_symbol.upper())

def handler(event, context):
    """
    Die Hauptfunktion, die von Netlify Functions aufgerufen wird.
    Empfängt den HTTP-Request, ruft yfinance auf und gibt JSON zurück.
    """
    logger.info("Netlify Function 'getStockData' wurde aufgerufen.")
    
    query_params = event.get('queryStringParameters')
    if not query_params or 'symbol' not in query_params:
        logger.warning("Fehler: 'symbol' Parameter fehlt im Request.")
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Symbol-Parameter fehlt. Bitte geben Sie ein gültiges Symbol, WKN oder ISIN ein.'}),
            'headers': {'Content-Type': 'application/json'}
        }

    input_symbol = query_params['symbol']
    # Konvertiere die Eingabe zu einem Yahoo Finance Symbol
    symbol = convert_to_yahoo_symbol(input_symbol)
    logger.info(f"Anfrage für Input: {input_symbol}, konvertiert zu Yahoo Symbol: {symbol}")

    try:
        ticker = yf.Ticker(symbol)

        # --- Aktuelle Daten abrufen ---
        info = ticker.info
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
                raise ValueError("Keine aktuellen Preisdaten gefunden.")
        else:
            current_price = info.get('currentPrice')
            previous_close = info.get('previousClose')

        long_name = info.get('longName', symbol)
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
            # yfinance gibt die neuesten Daten zuerst, wir wollen die ältesten zuerst für den Chart
            # Die Sortierung ist bereits implizit, da wir in prices.append() die Daten chronologisch hinzufügen

        # --- Dividenden abrufen (letzte 10 Jahre) ---
        dividends_df = ticker.dividends
        dividends = []
        if not dividends_df.empty:
            current_year = datetime.now().year
            annual_dividends = {}
            # Aggregiere Dividenden pro Jahr
            for index, value in dividends_df.items():
                div_year = index.year
                # Beachte: yfinance kann auch zukünftige (angekündigte) Dividenden liefern.
                # Hier filtern wir für die letzten 10 vollen Jahre + das aktuelle Jahr, falls schon Ausschüttungen waren
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
                # Suche die Dividende des letzten abgeschlossenen Jahres
                last_full_year_dividend = 0
                for div in dividends:
                    if div['year'] == (current_year - 1) or (div['year'] == current_year and datetime.now().month >= 11): # Annahme: Wenn Nov/Dez, dann ist dieses Jahr fast voll
                        last_full_year_dividend = div['amount']
                        break
                if last_full_year_dividend > 0:
                    dividend_yield = (last_full_year_dividend / current_price) * 100

        response_data = {
            "symbol": symbol,
            "companyName": long_name,
            "prices": prices,
            "currency": currency,
            "currentPrice": round(current_price, 2) if current_price is not None else None,
            "previousClose": round(previous_close, 2) if previous_close is not None else None,
            "marketChange": round(market_change, 2) if market_change is not None else None,
            "marketChangePercent": round(market_change_percent, 2) if market_change_percent is not None else None,
            "dividends": dividends,
            "dividendYield": round(dividend_yield, 2)
        }
        
        logger.info(f"Daten für {symbol} erfolgreich abgerufen.")
        return {
            'statusCode': 200,
            'body': json.dumps(response_data),
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*' # Erlaubt CORS-Zugriff von jedem Ursprung
            }
        }

    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Daten für {symbol}: {e}", exc_info=True)
        error_message = f"Fehler beim Abrufen der Daten für '{input_symbol}'. Möglicherweise ist das Symbol ungültig oder es gab ein temporäres Problem. Details: {str(e)}"
        
        if "No data found for this date range" in str(e) or "empty DataFrame" in str(e):
             error_message = f"Für '{input_symbol}' wurden keine Daten gefunden. Bitte prüfen Sie das Symbol."
        elif "Invalid input" in str(e):
             error_message = f"Ungültiges Symbol '{input_symbol}'. Bitte verwenden Sie ein gültiges Yahoo Finance Symbol, WKN oder ISIN."

        return {
            'statusCode': 500, # Interner Serverfehler
            'body': json.dumps({'error': error_message}),
            'headers': {'Content-Type': 'application/json'}
        }

