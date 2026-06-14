import sqlite3
import time

DB_NAME = "xt_scanner.db"

def init_db():
    conn = sqlite3.connect(DB_NAME, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute('PRAGMA journal_mode=WAL')
    cursor.execute('PRAGMA synchronous=NORMAL')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS coin_history (
            timestamp INTEGER,
            symbol TEXT,
            price REAL,
            buy_vol_1m REAL,
            sell_vol_1m REAL,
            UNIQUE(timestamp, symbol)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS last_snapshot (
            symbol TEXT PRIMARY KEY,
            volume_24h REAL,
            price REAL,
            cum_buy REAL DEFAULT 0,
            cum_sell REAL DEFAULT 0
        )
    ''')
    
    # Create indexes for faster querying
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON coin_history(timestamp)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_symbol ON coin_history(symbol)')
    
    # Auto-migrate: add cum_buy and cum_sell if missing
    try:
        cursor.execute('ALTER TABLE last_snapshot ADD COLUMN cum_buy REAL DEFAULT 0')
    except sqlite3.OperationalError:
        pass # Column already exists
        
    try:
        cursor.execute('ALTER TABLE last_snapshot ADD COLUMN cum_sell REAL DEFAULT 0')
    except sqlite3.OperationalError:
        pass # Column already exists
        
    conn.commit()
    conn.close()

def insert_snapshots(data):
    """
    data is a list of dicts: [{'symbol': 'btc_usdt', 'price': 60000, 'volume_24h': 1000000}]
    """
    current_time = int(time.time())
    
    conn = sqlite3.connect(DB_NAME, timeout=10.0)
    cursor = conn.cursor()
    
    # Get last snapshots to calculate 1m volume difference and price diff
    cursor.execute('SELECT symbol, volume_24h, price, cum_buy, cum_sell FROM last_snapshot')
    last_vols = {row[0]: {'volume_24h': row[1], 'price': row[2], 'cum_buy': row[3] or 0, 'cum_sell': row[4] or 0} for row in cursor.fetchall()}
    
    history_records = []
    snapshot_records = []
    
    for item in data:
        sym = item['symbol']
        curr_vol = float(item.get('volume_24h', 0))
        price = float(item.get('price', 0))
        
        # Calculate 1m volume
        prev_data = last_vols.get(sym, {'volume_24h': curr_vol, 'price': price, 'cum_buy': 0, 'cum_sell': 0})
        prev_vol = prev_data['volume_24h']
        prev_price = prev_data['price']
        cum_buy = prev_data['cum_buy']
        cum_sell = prev_data['cum_sell']
        
        vol_1m = max(0, curr_vol - prev_vol)
        
        buy_vol = 0
        sell_vol = 0
        
        # If it's the very first time we see this coin, 1m vol is 0
        if sym not in last_vols:
            vol_1m = 0
            
        if price >= prev_price:
            buy_vol = vol_1m
            cum_buy += vol_1m
        else:
            sell_vol = vol_1m
            cum_sell += vol_1m
            
        history_records.append((current_time, sym, price, buy_vol, sell_vol))
        snapshot_records.append((sym, curr_vol, price, cum_buy, cum_sell))
        
    cursor.executemany('''
        INSERT OR IGNORE INTO coin_history (timestamp, symbol, price, buy_vol_1m, sell_vol_1m)
        VALUES (?, ?, ?, ?, ?)
    ''', history_records)
    
    cursor.executemany('''
        INSERT OR REPLACE INTO last_snapshot (symbol, volume_24h, price, cum_buy, cum_sell)
        VALUES (?, ?, ?, ?, ?)
    ''', snapshot_records)
    
    # Cleanup old records (older than 24 hours)
    cutoff_time = current_time - (24 * 60 * 60)
    cursor.execute('DELETE FROM coin_history WHERE timestamp < ?', (cutoff_time,))
    
    conn.commit()
    conn.close()

def get_dashboard_data():
    """
    Calculates 5m, 15m, 1h, 4h, 24h buy/sell volumes and price changes for all coins.
    """
    current_time = int(time.time())
    conn = sqlite3.connect(DB_NAME, timeout=10.0)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    t_5m = current_time - (5 * 60)
    t_15m = current_time - (15 * 60)
    t_1h = current_time - (60 * 60)
    t_4h = current_time - (4 * 60 * 60)
    t_24h = current_time - (24 * 60 * 60)
    
    query = f'''
        SELECT 
            ch1.symbol,
            (SELECT price FROM coin_history ch2 WHERE ch2.symbol = ch1.symbol ORDER BY timestamp DESC LIMIT 1) as current_price,
            ls.cum_buy,
            ls.cum_sell,
            SUM(CASE WHEN timestamp >= {t_5m} THEN buy_vol_1m ELSE 0 END) as buy_vol_5m,
            SUM(CASE WHEN timestamp >= {t_5m} THEN sell_vol_1m ELSE 0 END) as sell_vol_5m,
            
            SUM(CASE WHEN timestamp >= {t_15m} THEN buy_vol_1m ELSE 0 END) as buy_vol_15m,
            SUM(CASE WHEN timestamp >= {t_15m} THEN sell_vol_1m ELSE 0 END) as sell_vol_15m,
            
            SUM(CASE WHEN timestamp >= {t_1h} THEN buy_vol_1m ELSE 0 END) as buy_vol_1h,
            SUM(CASE WHEN timestamp >= {t_1h} THEN sell_vol_1m ELSE 0 END) as sell_vol_1h,
            
            SUM(CASE WHEN timestamp >= {t_4h} THEN buy_vol_1m ELSE 0 END) as buy_vol_4h,
            SUM(CASE WHEN timestamp >= {t_4h} THEN sell_vol_1m ELSE 0 END) as sell_vol_4h,
            
            SUM(CASE WHEN timestamp >= {t_24h} THEN buy_vol_1m ELSE 0 END) as buy_vol_24h,
            SUM(CASE WHEN timestamp >= {t_24h} THEN sell_vol_1m ELSE 0 END) as sell_vol_24h
        FROM coin_history ch1
        LEFT JOIN last_snapshot ls ON ch1.symbol = ls.symbol
        GROUP BY ch1.symbol
    '''
    
    cursor.execute(query)
    rows = cursor.fetchall()
    
    results = []
    for row in rows:
        vol_5m_total = (row['buy_vol_5m'] or 0) + (row['sell_vol_5m'] or 0)
        results.append({
            'symbol': row['symbol'].upper().replace('_', '/'),
            'price': row['current_price'] or 0,
            'buy_vol_5m': row['buy_vol_5m'] or 0,
            'sell_vol_5m': row['sell_vol_5m'] or 0,
            'buy_vol_15m': row['buy_vol_15m'] or 0,
            'sell_vol_15m': row['sell_vol_15m'] or 0,
            'buy_vol_1h': row['buy_vol_1h'] or 0,
            'sell_vol_1h': row['sell_vol_1h'] or 0,
            'buy_vol_4h': row['buy_vol_4h'] or 0,
            'sell_vol_4h': row['sell_vol_4h'] or 0,
            'buy_vol_24h': row['buy_vol_24h'] or 0,
            'sell_vol_24h': row['sell_vol_24h'] or 0,
            'cum_buy': row['cum_buy'] or 0,
            'cum_sell': row['cum_sell'] or 0,
            'vol_5m_total': vol_5m_total
        })
        
    conn.close()
    
    # Sort by 5m total volume to see what's moving
    results.sort(key=lambda x: x['vol_5m_total'], reverse=True)
    return results
