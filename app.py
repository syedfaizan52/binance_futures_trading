from flask import Flask, render_template, request, jsonify
from binance.client import Client
from binance import ThreadedWebsocketManager
import os
import threading

app = Flask(__name__)

# Load Binance API keys from environment variables
api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_API_SECRET')

# Check if API keys are set
if not api_key or not api_secret:
    raise ValueError("Binance API key and secret must be set as environment variables.")

client = Client(api_key, api_secret)

# Global variables to store market data
market_data = {}

def fetch_market_data():
    """Fetch top 10 USDT-based coins by 24h volume."""
    tickers = client.get_ticker()
    # Filter USDT pairs and sort by quote volume (most traded)
    usdt_pairs = [ticker for ticker in tickers if ticker['symbol'].endswith('USDT')]
    top_coins = sorted(usdt_pairs, key=lambda x: float(x['quoteVolume']), reverse=True)[:10]
    return top_coins

def calculate_levels(symbol):
    """Calculate stop-loss and take-profit levels based on ATR."""
    klines = client.get_klines(symbol=symbol, interval='1h', limit=14)
    atr = sum(float(k[2]) - float(k[3]) for k in klines) / 14  # Simple ATR calculation
    last_price = float(klines[-1][4])  # Last closing price
    stop_loss = last_price - (atr * 1.5)  # Stop-loss at 1.5x ATR
    take_profit = last_price + (atr * 1.5)  # Take-profit at 1.5x ATR
    return stop_loss, take_profit

def start_websocket():
    """Start WebSocket to fetch real-time market data for USDT pairs."""
    def handle_socket_message(msg):
        """Handle incoming WebSocket messages."""
        if 's' in msg and 'c' in msg and msg['s'].endswith('USDT'):
            symbol = msg['s']
            price = msg['c']
            market_data[symbol] = price

    twm = ThreadedWebsocketManager(api_key=api_key, api_secret=api_secret)
    twm.start()

    # Subscribe to ticker streams for top USDT pairs
    top_coins = fetch_market_data()
    for coin in top_coins:
        symbol = coin['symbol']
        twm.start_symbol_ticker_socket(callback=handle_socket_message, symbol=symbol)

# Start WebSocket in a separate thread
threading.Thread(target=start_websocket, daemon=True).start()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_suggestions', methods=['GET'])
def get_suggestions():
    top_coins = fetch_market_data()
    suggestions = []
    for coin in top_coins:
        symbol = coin['symbol']
        stop_loss, take_profit = calculate_levels(symbol)
        suggestions.append({
            'symbol': symbol,
            'price': market_data.get(symbol, coin['lastPrice']),  # Use real-time data if available
            'stop_loss': stop_loss,
            'take_profit': take_profit
        })
    return jsonify(suggestions)

@app.route('/place_order', methods=['POST'])
def place_order():
    data = request.json
    symbol = data['symbol']
    side = data['side']
    quantity = data['quantity']
    stop_loss = data['stop_loss']
    take_profit = data['take_profit']
    entry_price = data.get('entry_price')  # Optional, not used for MARKET orders

    # Place the order
    order = client.futures_create_order(
        symbol=symbol,
        side=side,
        type='MARKET',
        quantity=quantity
    )

    # Place stop loss and take profit orders
    stop_loss_order = client.futures_create_order(
        symbol=symbol,
        side='SELL' if side == 'BUY' else 'BUY',
        type='STOP_MARKET',
        quantity=quantity,
        stopPrice=stop_loss
    )

    take_profit_order = client.futures_create_order(
        symbol=symbol,
        side='SELL' if side == 'BUY' else 'BUY',
        type='TAKE_PROFIT_MARKET',
        quantity=quantity,
        stopPrice=take_profit
    )

    return jsonify({
        'order': order,
        'stop_loss_order': stop_loss_order,
        'take_profit_order': take_profit_order,
        'entry_price': entry_price  # Include entry price in the response
    })

if __name__ == '__main__':
    app.run(debug=True)
