from flask import Flask, render_template, jsonify
import threading
import time
import urllib.request
import json
import ssl

try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

from database import init_db, insert_snapshots, get_dashboard_data
import time as time_module
import threading

app = Flask(__name__)

# Initialize the database
init_db()

WALLS_CACHE = {}
DASHBOARD_CACHE = {'data': None, 'time': 0}
CACHE_LOCK = threading.Lock()

def get_cached_dashboard_data():
    return DASHBOARD_CACHE.get('data') or []

def fetch_order_books():
    """Background task to fetch order book depth for the top 20 coins by 5m volume."""
    print("[*] Order Book collection thread started...")
    while True:
        try:
            dashboard_data = get_cached_dashboard_data()
            if dashboard_data:
                # Sort by 5m total volume (buy + sell)
                sorted_coins = sorted(
                    dashboard_data, 
                    key=lambda x: x.get('buy_vol_5m', 0) + x.get('sell_vol_5m', 0), 
                    reverse=True
                )
                top_20 = [c['symbol'] for c in sorted_coins[:20]]
                
                for symbol in top_20:
                    api_sym = symbol.lower().replace('/', '_')
                    req_ob = urllib.request.Request(
                        f'https://sapi.xt.com/v4/public/depth?symbol={api_sym}&limit=500',
                        headers={'User-Agent': 'Mozilla/5.0'}
                    )
                    req_kl = urllib.request.Request(
                        f'https://sapi.xt.com/v4/public/kline?symbol={api_sym}&interval=1h&limit=24',
                        headers={'User-Agent': 'Mozilla/5.0'}
                    )
                    try:
                        resp_ob = urllib.request.urlopen(req_ob, timeout=3)
                        data_ob = json.loads(resp_ob.read())
                        
                        resp_kl = urllib.request.urlopen(req_kl, timeout=3)
                        data_kl = json.loads(resp_kl.read())
                        
                        buy_wall = None
                        sell_wall = None
                        bounce_at = None
                        reject_at = None
                        
                        if data_ob.get('rc') == 0:
                            bids = data_ob['result']['bids']
                            asks = data_ob['result']['asks']
                            buy_wall = sum(float(b[0]) * float(b[1]) for b in bids[:50]) # Keep walls metric to top 50 for consistency
                            sell_wall = sum(float(a[0]) * float(a[1]) for a in asks[:50])
                            
                            top_bids = []
                            top_asks = []
                            
                            # Find top 5 biggest order levels in all 500 levels
                            if bids:
                                sorted_bids = sorted(bids, key=lambda x: float(x[0]) * float(x[1]), reverse=True)
                                top_bids = [{'price': float(b[0]), 'value': float(b[0]) * float(b[1])} for b in sorted_bids[:5]]
                                bounce_at = float(sorted_bids[0][0]) if sorted_bids else None
                            if asks:
                                sorted_asks = sorted(asks, key=lambda x: float(x[0]) * float(x[1]), reverse=True)
                                top_asks = [{'price': float(a[0]), 'value': float(a[0]) * float(a[1])} for a in sorted_asks[:5]]
                                reject_at = float(sorted_asks[0][0]) if sorted_asks else None
                            
                        support = None
                        resistance = None
                        if data_kl.get('rc') == 0 and data_kl.get('result'):
                            klines = data_kl['result']
                            support = min(float(k['l']) for k in klines)
                            resistance = max(float(k['h']) for k in klines)
                            
                        WALLS_CACHE[symbol] = {
                            'buy_wall': buy_wall,
                            'sell_wall': sell_wall,
                            'bounce_at': bounce_at,
                            'reject_at': reject_at,
                            'support': support,
                            'resistance': resistance,
                            'top_bids': top_bids,
                            'top_asks': top_asks
                        }
                        time.sleep(0.5) # Prevent rate limit
                    except Exception as e:
                        pass
        except Exception as e:
            print(f"[ERROR] Order Book thread: {e}")
            
        time.sleep(15)

def fetch_xt_data():
    """Background task to fetch data from XT API every 60 seconds"""
    print("[*] Background data collection thread started...")
    while True:
        try:
            req = urllib.request.Request(
                'https://sapi.xt.com/v4/public/ticker/24h',
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            response = urllib.request.urlopen(req)
            data = json.loads(response.read())
            
            # Filter USDT pairs and format
            tickers = []
            for t in data.get('result', []):
                sym = t.get('s', '')
                if sym.endswith('_usdt'):
                    tickers.append({
                        'symbol': sym,
                        'price': float(t.get('c', 0)), # 'c' is latest price
                        'volume_24h': float(t.get('v', 0)) # 'v' is 24h volume
                    })
            
            if tickers:
                insert_snapshots(tickers)
                print(f"[OK] Data fetched and saved at {time.strftime('%H:%M:%S')}")
                
        except Exception as e:
            print(f"[ERROR] Error fetching data: {e}")
            
        time.sleep(10)

def dashboard_updater_loop():
    """Background task to update dashboard cache every 5 seconds without blocking users"""
    print("[*] Background Dashboard Updater started...")
    while True:
        try:
            new_data = get_dashboard_data()
            if new_data:
                DASHBOARD_CACHE['data'] = new_data
                DASHBOARD_CACHE['time'] = time_module.time()
        except Exception as e:
            print(f"[ERROR] Error updating dashboard cache: {e}")
        time_module.sleep(5)

# Start background threads
bg_thread = threading.Thread(target=fetch_xt_data, daemon=True)
bg_thread.start()

ob_thread = threading.Thread(target=fetch_order_books, daemon=True)
ob_thread.start()

db_thread = threading.Thread(target=dashboard_updater_loop, daemon=True)
db_thread.start()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/data')
def api_data():
    try:
        data = get_cached_dashboard_data()
        # Merge walls cache and calculate predictions
        for coin in data:
            sym = coin['symbol']
            bw = None
            sw = None
            sup = None
            res = None
            bounce = None
            reject = None
            if sym in WALLS_CACHE:
                bw = WALLS_CACHE[sym]['buy_wall']
                sw = WALLS_CACHE[sym]['sell_wall']
                sup = WALLS_CACHE[sym].get('support')
                res = WALLS_CACHE[sym].get('resistance')
                bounce = WALLS_CACHE[sym].get('bounce_at')
                reject = WALLS_CACHE[sym].get('reject_at')
                
                coin['buy_wall'] = bw
                coin['sell_wall'] = sw
                coin['support'] = sup
                coin['resistance'] = res
                coin['bounce_at'] = bounce
                coin['reject_at'] = reject
            else:
                coin['buy_wall'] = None
                coin['sell_wall'] = None
                coin['support'] = None
                coin['resistance'] = None
                coin['bounce_at'] = None
                coin['reject_at'] = None
            
            # AI Prediction Scoring Logic
            score = 0
            
            # 1. 5m Volume Momentum (Max +/- 40 points)
            b_5m = coin.get('buy_vol_5m', 0)
            s_5m = coin.get('sell_vol_5m', 0)
            t_5m = b_5m + s_5m
            
            if t_5m > 5000: # Only score if there's meaningful volume
                if b_5m > s_5m * 3: score += 40
                elif b_5m > s_5m * 1.5: score += 20
                elif s_5m > b_5m * 3: score -= 40
                elif s_5m > b_5m * 1.5: score -= 20

            # 2. 15m Trend (Max +/- 20 points)
            b_15m = coin.get('buy_vol_15m', 0)
            s_15m = coin.get('sell_vol_15m', 0)
            if (b_15m + s_15m) > 10000:
                if b_15m > s_15m * 2: score += 20
                elif s_15m > b_15m * 2: score -= 20
                
            # 3. Order Book Walls (Max +/- 30 points)
            if bw is not None and sw is not None and (bw + sw) > 1000:
                if bw > sw * 3: score += 30
                elif bw > sw * 1.5: score += 15
                elif sw > bw * 3: score -= 30
                elif sw > bw * 1.5: score -= 15
                
            # Cap score between -90 to +90
            score = max(-90, min(90, score))
            
            # Translate score to probability
            prob = abs(score) + 5 # Base 5% noise
            direction = "UP" if score > 0 else "DOWN" if score < 0 else "NEUTRAL"
            
            if direction == "NEUTRAL" or prob < 20:
                coin['ai_pred'] = {'prob': 0, 'dir': 'NEUTRAL', 'exp': '0%'}
            else:
                # Estimate expected move based on 5m volume relative to 24h
                t_24h = coin.get('buy_vol_24h', 0) + coin.get('sell_vol_24h', 0)
                exp_pct = "1-2%"
                if t_24h > 0 and t_5m > 0:
                    spike_ratio = t_5m / t_24h
                    if spike_ratio > 0.05: # 5% of daily volume in 5 mins! Massive.
                        exp_pct = "5-10%"
                    elif spike_ratio > 0.01:
                        exp_pct = "2-5%"
                
                target_str = ""
                if direction == 'UP' and res is not None:
                    target_str = f"🎯 Tgt: ${res:.4f}" if res < 1 else f"🎯 Tgt: ${res:.2f}"
                elif direction == 'DOWN' and sup is not None:
                    target_str = f"🎯 Tgt: ${sup:.4f}" if sup < 1 else f"🎯 Tgt: ${sup:.2f}"
                    
                # Pump / Dump Alert Logic
                alert = None
                warning = None
                
                b_1h = coin.get('buy_vol_1h', 0)
                s_1h = coin.get('sell_vol_1h', 0)
                t_24h = coin.get('buy_vol_24h', 0) + coin.get('sell_vol_24h', 0)
                
                if b_5m + s_5m > 10000: # Minimum $10k volume in 5m to avoid noise
                    if b_5m > s_5m * 4:
                        if b_5m > 15000 and t_24h > 0 and (b_5m / t_24h >= 0.05) and (not sw or bw > sw):
                            alert = 'BREAKOUT'
                        elif (sw and bw and sw > bw * 3) or (s_15m > b_15m * 1.5) or (s_1h > b_1h * 1.5):
                            warning = 'FAKE_PUMP'
                        elif (not bw or not sw or bw > sw * 1.2):
                            alert = 'PUMP'
                    elif s_5m > b_5m * 4:
                        if (bw and sw and bw > sw * 3) or (b_15m > s_15m * 1.5) or (b_1h > s_1h * 1.5):
                            warning = 'FAKE_DUMP'
                        elif (not bw or not sw or sw > bw * 1.2):
                            alert = 'DUMP'
                        
                coin['alert'] = alert
                coin['warning'] = warning
                coin['ai_pred'] = {
                    'prob': prob,
                    'dir': direction,
                    'exp': f"{'+' if direction == 'UP' else '-'}{exp_pct}",
                    'target': target_str
                }
                
        return jsonify({'status': 'success', 'data': data})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

from flask import request

@app.route('/api/depth')
def api_depth():
    symbol = request.args.get('symbol')
    if not symbol:
        return jsonify({'status': 'error', 'message': 'Symbol required'})
    
    api_sym = symbol.lower().replace('/', '_')
    try:
        req = urllib.request.Request(
            f'https://sapi.xt.com/v4/public/depth?symbol={api_sym}&limit=500',
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read())
        if data.get('rc') == 0:
            bids = data['result']['bids']
            asks = data['result']['asks']
            buy_wall = sum(float(b[0]) * float(b[1]) for b in bids[:50])
            sell_wall = sum(float(a[0]) * float(a[1]) for a in asks[:50])
            
            bounce_at = None
            reject_at = None
            if bids:
                biggest_bid = max(bids, key=lambda x: float(x[0]) * float(x[1]))
                bounce_at = float(biggest_bid[0])
            if asks:
                biggest_ask = max(asks, key=lambda x: float(x[0]) * float(x[1]))
                reject_at = float(biggest_ask[0])
            
            # Update cache since we fetched it
            WALLS_CACHE[symbol] = {
                'buy_wall': buy_wall,
                'sell_wall': sell_wall,
                'bounce_at': bounce_at,
                'reject_at': reject_at,
                'support': WALLS_CACHE.get(symbol, {}).get('support'),
                'resistance': WALLS_CACHE.get(symbol, {}).get('resistance')
            }
            return jsonify({'status': 'success', 'buy_wall': buy_wall, 'sell_wall': sell_wall, 'bounce_at': bounce_at, 'reject_at': reject_at})
        else:
            return jsonify({'status': 'error', 'message': 'API Error'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/analysis/<symbol>')
def analysis_page(symbol):
    # Symbol comes in as BTC_USDT, we pass it to template
    real_symbol = symbol.replace('_', '/')
    return render_template('analysis.html', symbol=real_symbol, url_symbol=symbol)

@app.route('/api/analysis')
def api_analysis():
    symbol = request.args.get('symbol')
    if not symbol:
        return jsonify({'status': 'error', 'message': 'Symbol required'})
        
    real_symbol = symbol.replace('_', '/')
    data = get_cached_dashboard_data()
    coin = next((c for c in data if c['symbol'] == real_symbol), None)
    
    if not coin:
        return jsonify({'status': 'error', 'message': 'Coin not found'})
        
    cache = WALLS_CACHE.get(real_symbol, {})
    
    # If not in cache (e.g. not a top 20 volume coin), fetch it now
    if not cache or not cache.get('top_bids'):
        try:
            api_sym = real_symbol.lower().replace('/', '_')
            req_ob = urllib.request.Request(
                f'https://sapi.xt.com/v4/public/depth?symbol={api_sym}&limit=50',
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            resp_ob = urllib.request.urlopen(req_ob, timeout=3)
            data_ob = json.loads(resp_ob.read())
            if data_ob.get('rc') == 0:
                bids = data_ob['result']['bids']
                asks = data_ob['result']['asks']
                
                if bids:
                    sorted_bids = sorted(bids, key=lambda x: float(x[0]) * float(x[1]), reverse=True)
                    top_bids = [{'price': float(b[0]), 'value': float(b[0]) * float(b[1])} for b in sorted_bids[:5]]
                    cache['bounce_at'] = float(sorted_bids[0][0])
                    cache['top_bids'] = top_bids
                    cache['buy_wall'] = sum(float(b[0]) * float(b[1]) for b in bids)
                if asks:
                    sorted_asks = sorted(asks, key=lambda x: float(x[0]) * float(x[1]), reverse=True)
                    top_asks = [{'price': float(a[0]), 'value': float(a[0]) * float(a[1])} for a in sorted_asks[:5]]
                    cache['reject_at'] = float(sorted_asks[0][0])
                    cache['top_asks'] = top_asks
                    cache['sell_wall'] = sum(float(a[0]) * float(a[1]) for a in asks)
                    
                WALLS_CACHE[real_symbol] = cache
        except Exception as e:
            print(f"Error inline fetch {real_symbol}: {e}")

    price = coin.get('price', 0)
    
    # Run prediction logic (simplified)
    b_5m = coin.get('buy_vol_5m', 0)
    s_5m = coin.get('sell_vol_5m', 0)
    score = 0
    if b_5m + s_5m > 5000:
        if b_5m > s_5m * 3: score += 40
        elif b_5m > s_5m * 1.5: score += 20
        elif s_5m > b_5m * 3: score -= 40
        elif s_5m > b_5m * 1.5: score -= 20
        
    direction = "UP" if score > 0 else "DOWN" if score < 0 else "NEUTRAL"
    prob = abs(score) + 5
    if prob < 20: direction = "NEUTRAL"
    
    sup = cache.get('support', price * 0.95)
    res = cache.get('resistance', price * 1.05)
    bounce = cache.get('bounce_at', sup)
    reject = cache.get('reject_at', res)
    
    b_15m = coin.get('buy_vol_15m', 0)
    s_15m = coin.get('sell_vol_15m', 0)
    b_1h = coin.get('buy_vol_1h', 0)
    s_1h = coin.get('sell_vol_1h', 0)
    t_24h = coin.get('buy_vol_24h', 0) + coin.get('sell_vol_24h', 0)
    
    alert = None
    bw = cache.get('buy_wall')
    sw = cache.get('sell_wall')
    if b_5m + s_5m > 10000:
        if b_5m > s_5m * 4:
            if b_5m > 15000 and t_24h > 0 and (b_5m / t_24h >= 0.05) and (not sw or bw > sw):
                alert = 'BREAKOUT'
            elif (not bw or not sw or bw > sw * 1.2):
                alert = 'PUMP'
        elif s_5m > b_5m * 4:
            if (not bw or not sw or sw > bw * 1.2):
                alert = 'DUMP'

    setup = {
        'symbol': real_symbol,
        'price': price,
        'direction': direction,
        'prob': prob,
        'alert': alert,
        'spot': {},
        'futures': {},
        'explanation': '',
        'volume': {
            '5m': {'buy': b_5m, 'sell': s_5m},
            '15m': {'buy': b_15m, 'sell': s_15m},
            '1h': {'buy': b_1h, 'sell': s_1h},
            '4h': {'buy': coin.get('buy_vol_4h', 0), 'sell': coin.get('sell_vol_4h', 0)},
            '24h': {'buy': coin.get('buy_vol_24h', 0), 'sell': coin.get('sell_vol_24h', 0)},
            'cum': {'buy': coin.get('cum_buy', 0), 'sell': coin.get('cum_sell', 0)}
        },
        'walls': {
            'buy_wall': bw,
            'sell_wall': sw,
            'bounce': bounce,
            'reject': reject,
            'top_bids': cache.get('top_bids', []),
            'top_asks': cache.get('top_asks', [])
        }
    }
    
    top_asks = cache.get('top_asks', [])
    top_bids = cache.get('top_bids', [])
    
    if direction == 'UP':
        # UP Setup
        sl = bounce * 0.995 if bounce else price * 0.98 # Just below bounce wall
        
        # Calculate multiple TPs based on top resistance walls
        tps = [a['price'] * 0.995 for a in top_asks if a['price'] > price]
        tps = sorted(list(set(tps)))[:3] # Get top 3 unique TPs
        if not tps:
            tps = [price * 1.02, price * 1.05, price * 1.08]
            
        tp = tps[0] if tps else price * 1.05
        
        setup['spot'] = {'entry': price, 'sl': sl, 'tp': tp, 'tps': tps}
        setup['futures'] = {'entry': price, 'sl': price - ((price - sl)*0.5), 'tp': price + ((tp - price)*0.8), 'tps': tps}
        
        setup['explanation'] = f"5 நிமிடங்களில் வாங்குபவர்கள் (Buyers) ஆதிக்கம் செலுத்துகிறார்கள். மார்க்கெட் {prob}% ஏறுவதற்கான வாய்ப்புள்ளது. Order Book-ல் {bounce} விலையில் பெரிய Buy Wall உள்ளதால் அதுவே சிறந்த Stop Loss."
        
    elif direction == 'DOWN':
        # DOWN Setup
        sl = reject * 1.005 if reject else price * 1.02 # Just above reject wall
        
        # Calculate multiple TPs based on top support walls
        tps = [b['price'] * 1.005 for b in top_bids if b['price'] < price]
        tps = sorted(list(set(tps)), reverse=True)[:3] # Get top 3 unique TPs (closest to price first)
        if not tps:
            tps = [price * 0.98, price * 0.95, price * 0.92]
            
        tp = tps[0] if tps else price * 0.95
        
        setup['spot'] = {'entry': price, 'sl': sl, 'tp': tp, 'tps': tps}
        setup['futures'] = {'entry': price, 'sl': price + ((sl - price)*0.5), 'tp': price - ((price - tp)*0.8), 'tps': tps}
        
        setup['explanation'] = f"5 நிமிடங்களில் விற்பவர்கள் (Sellers) ஆதிக்கம் செலுத்துகிறார்கள். மார்க்கெட் {prob}% கீழே சரிவதற்கான வாய்ப்புள்ளது. {reject} விலையில் பெரிய Sell Wall உள்ளதால் அதை Stop Loss ஆகப் பயன்படுத்தலாம்."
        
    else:
        # Provide default setup for Neutral (assume basic long for reference)
        sl = bounce * 0.99 if bounce else price * 0.95
        tps = [a['price'] * 0.995 for a in top_asks if a['price'] > price]
        tps = sorted(list(set(tps)))[:3]
        if not tps:
            tps = [price * 1.02, price * 1.05, price * 1.08]
        tp = tps[0] if tps else price * 1.05
        
        setup['spot'] = {'entry': price, 'sl': sl, 'tp': tp, 'tps': tps}
        setup['futures'] = {'entry': price, 'sl': price - ((price - sl)*0.5), 'tp': price + ((tp - price)*0.8), 'tps': tps}
        
        setup['explanation'] = "தற்போது மார்க்கெட் எந்தத் திசையிலும் வலுவாக நகரவில்லை. வால்யூம் மிகவும் சமநிலையில் உள்ளது (Neutral). ட்ரேடிங் செய்வதைத் தவிர்ப்பது நல்லது."
        
    return jsonify({'status': 'success', 'data': setup})

if __name__ == '__main__':
    # Run the app on 0.0.0.0 to allow mobile network access
    app.run(host='0.0.0.0', port=5000, debug=False)
