from http.server import BaseHTTPRequestHandler
import json
import yfinance as yf # yfinance ist jetzt installiert und kann hier importiert werden

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            # 1. Definiere das Aktiensymbol, das du abfragen möchtest
            # Du könntest dies später auch dynamisch über URL-Parameter machen
            ticker_symbol = "AAPL" # Beispiel: Apple Inc.

            # 2. Verwende yfinance, um Ticker-Objekt zu erhalten
            ticker = yf.Ticker(ticker_symbol)

            # 3. Lade die historischen Daten für die letzten 5 Tage
            # Oder .info für allgemeine Informationen, .dividends, .splits etc.
            hist_data = ticker.history(period="5d")

            # 4. Bereite die Daten für die JSON-Antwort auf
            # Die hist_data ist ein Pandas DataFrame, das müssen wir für JSON umwandeln.
            # .to_json() ist hier sehr nützlich.
            # index=True stellt sicher, dass das Datum (Index) auch im JSON ist.
            hist_data_json = hist_data.to_json(orient="index", date_format="iso")
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            response = {
                "message": f"Successfully fetched data for {ticker_symbol}",
                "symbol": ticker_symbol,
                "data": json.loads(hist_data_json) # Parse den JSON-String zurück in ein Python-Dict
            }
            self.wfile.write(json.dumps(response).encode('utf-8'))
            
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*') 
            self.end_headers()
            
            response = {"error": f"Failed to fetch data or server error: {str(e)}"}
            self.wfile.write(json.dumps(response).encode('utf-8'))

