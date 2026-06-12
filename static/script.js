let previousData = {};
let currentCategory = 'all';
let currentVolFilter = 'all'; // 'all', 'buy', or 'sell'
let currentFilter = 'all';

// Hardcoded Categories
const MAJORS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT', 'ADA/USDT'];
const MEME_COINS = ['DOGE/USDT', 'SHIB/USDT', 'PEPE/USDT', 'FLOKI/USDT', 'BONK/USDT', 'WIF/USDT', 'BOME/USDT', 'MEME/USDT'];
const FOREX = ['EUR/USDT', 'GBP/USDT', 'AUD/USDT', 'JPY/USDT', 'CHF/USDT', 'CAD/USDT', 'NZD/USDT'];

// Theme Management
const themeToggle = document.getElementById('theme-toggle');
const currentTheme = localStorage.getItem('theme') || 'dark';

if (currentTheme === 'light') {
    document.documentElement.setAttribute('data-theme', 'light');
    themeToggle.innerHTML = '<i class="fa-solid fa-sun"></i>';
}

themeToggle.addEventListener('click', () => {
    let theme = document.documentElement.getAttribute('data-theme');
    if (theme === 'light') {
        document.documentElement.removeAttribute('data-theme');
        localStorage.setItem('theme', 'dark');
        themeToggle.innerHTML = '<i class="fa-solid fa-moon"></i>';
    } else {
        document.documentElement.setAttribute('data-theme', 'light');
        localStorage.setItem('theme', 'light');
        themeToggle.innerHTML = '<i class="fa-solid fa-sun"></i>';
    }
});

// Filter Handlers
document.querySelectorAll('.filter-btn[data-category]').forEach(btn => {
    btn.addEventListener('click', (e) => {
        document.querySelectorAll('.filter-btn[data-category]').forEach(b => b.classList.remove('active'));
        e.target.classList.add('active');
        currentCategory = e.target.getAttribute('data-category');
        updateDashboard();
    });
});

document.querySelectorAll('.filter-btn[data-vol]').forEach(btn => {
    btn.addEventListener('click', (e) => {
        document.querySelectorAll('.filter-btn[data-vol]').forEach(b => b.classList.remove('active'));
        e.currentTarget.classList.add('active');
        currentVolFilter = e.currentTarget.getAttribute('data-vol');
        updateDashboard();
    });
});

document.querySelectorAll('.filter-btn[data-filter]').forEach(btn => {
    btn.addEventListener('click', (e) => {
        document.querySelectorAll('.filter-btn[data-filter]').forEach(b => b.classList.remove('active'));
        e.currentTarget.classList.add('active');
        currentFilter = e.currentTarget.getAttribute('data-filter');
        updateDashboard();
    });
});


function formatCurrency(value) {
    if (value === null || value === undefined) return '0.00';
    if (value >= 1e6) {
        return (value / 1e6).toFixed(2) + 'M';
    } else if (value >= 1e3) {
        return (value / 1e3).toFixed(2) + 'K';
    }
    return Number(value).toFixed(2);
}

function renderValue(coinSymbol, valKey, currentVal) {
    let flashClass = '';
    const oldCoin = previousData[coinSymbol];
    
    if (oldCoin && currentVal > oldCoin[valKey]) {
        flashClass = 'flash-up';
    } else if (oldCoin && currentVal < oldCoin[valKey]) {
        flashClass = 'flash-down';
    }
    
    return `<span class="${flashClass}">$${formatCurrency(currentVal)}</span>`;
}

function formatVol(coin, buyKey, sellKey) {
    const buyHtml = renderValue(coin.symbol, buyKey, coin[buyKey]);
    const sellHtml = renderValue(coin.symbol, sellKey, coin[sellKey]);
    return `<span class="text-green">${buyHtml}</span> / <span class="text-red">${sellHtml}</span>`;
}

function renderPrice(coin) {
    let flashClass = '';
    const oldCoin = previousData[coin.symbol];
    if (oldCoin && coin.price > oldCoin.price) flashClass = 'flash-up text-green';
    else if (oldCoin && coin.price < oldCoin.price) flashClass = 'flash-down text-red';
    
    let p = coin.price || 0;
    return `<span class="${flashClass}">$${Number(p).toFixed(6)}</span>`;
}

let stickyAlerts = {};

function updateDashboard() {
    fetch('/api/data')
        .then(response => response.json())
        .then(res => {
            if (res.status === 'success') {
                cachedData = res.data;
                const tbody = document.getElementById('table-body');
                const searchInput = document.getElementById('search-input').value.toLowerCase();
                
                let topGainer = null;
                let visibleCount = 0;
                
                tbody.innerHTML = '';
                
                cachedData.forEach(coin => {
                    // Sticky Alerts Logic
                    if (coin.alert) {
                        stickyAlerts[coin.symbol] = { alert: coin.alert, timestamp: Date.now() };
                    } else if (stickyAlerts[coin.symbol]) {
                        const age = Date.now() - stickyAlerts[coin.symbol].timestamp;
                        const stickyAlert = stickyAlerts[coin.symbol].alert;
                        
                        // Clear sticky alert if AI Prediction completely contradicts it
                        let isContradicting = false;
                        if (coin.ai_pred) {
                            if ((stickyAlert === 'PUMP' || stickyAlert === 'BREAKOUT') && coin.ai_pred.dir === 'DOWN') isContradicting = true;
                            if (stickyAlert === 'DUMP' && coin.ai_pred.dir === 'UP') isContradicting = true;
                        }

                        if (age < 5 * 60 * 1000 && !isContradicting) { // Keep alive for 5 minutes if no contradiction
                            coin.alert = stickyAlert;
                        } else {
                            delete stickyAlerts[coin.symbol];
                        }
                    }

                    // Update top gainer
                    if (!topGainer || coin.buy_vol_5m > topGainer.buy_vol_5m) {
                        topGainer = coin;
                    }
                    
                    // Search filter
                    if (searchInput && !coin.symbol.toLowerCase().includes(searchInput)) return;
                    
                    // Category Filter Logic
                    if (currentCategory === 'majors' && !MAJORS.includes(coin.symbol)) return;
                    if (currentCategory === 'meme' && !MEME_COINS.includes(coin.symbol)) return;
                    if (currentCategory === 'forex' && !FOREX.includes(coin.symbol)) return;
                    if (currentCategory === 'altcoins') {
                        if (MAJORS.includes(coin.symbol) || MEME_COINS.includes(coin.symbol) || FOREX.includes(coin.symbol)) return;
                    }

                    // Volume Filter Logic
                    if (currentVolFilter === 'buy') {
                        if (coin.buy_vol_5m < coin.sell_vol_5m * 1.5 || coin.buy_vol_5m < 5000) return;
                    }
                    if (currentVolFilter === 'sell') {
                        if (coin.sell_vol_5m < coin.buy_vol_5m * 1.5 || coin.sell_vol_5m < 5000) return;
                    }

                    // State/AI Filter Logic
                    if (currentFilter === 'pump') if (coin.alert !== 'PUMP') return;
                    if (currentFilter === 'dump') if (coin.alert !== 'DUMP') return;
                    if (currentFilter === 'breakout') if (coin.alert !== 'BREAKOUT') return;
                    if (currentFilter === 'up') if (!coin.ai_pred || coin.ai_pred.dir !== 'UP') return;
                    if (currentFilter === 'down') if (!coin.ai_pred || coin.ai_pred.dir !== 'DOWN') return;
                    if (currentFilter === 'neutral') if (coin.ai_pred && coin.ai_pred.dir !== 'NEUTRAL') return;

                    visibleCount++;

                    const tr = document.createElement('tr');
                    
                    let vol5mClass = '';
                    if (coin.buy_vol_5m > 50000) {
                        vol5mClass = 'vol-spike';
                        if (!previousData[coin.symbol] || previousData[coin.symbol].buy_vol_5m !== coin.buy_vol_5m) {
                            document.getElementById('latest-alert').innerHTML = `🔥 ${coin.symbol} <span class="text-green">BUY SPIKE: +$${formatCurrency(coin.buy_vol_5m)}</span>`;
                        }
                    } else if (coin.sell_vol_5m > 50000) {
                        if (!previousData[coin.symbol] || previousData[coin.symbol].sell_vol_5m !== coin.sell_vol_5m) {
                            document.getElementById('latest-alert').innerHTML = `⚠️ ${coin.symbol} <span class="text-red">SELL SPIKE: -$${formatCurrency(coin.sell_vol_5m)}</span>`;
                        }
                    }

                    let wallHtml = `<span class="text-muted" style="cursor:pointer" onclick="fetchWall('${coin.symbol}')">[Click to Analyze]</span>`;
                    if (coin.buy_wall !== null && coin.sell_wall !== null) {
                        const bw = coin.buy_wall;
                        const sw = coin.sell_wall;
                        let highlight = '';
                        if (bw > sw * 3) highlight = '🚀 ';
                        if (sw > bw * 3) highlight = '⚠️ ';
                        
                        wallHtml = `${highlight}<span class="text-green">B: $${formatCurrency(bw)}</span> / <span class="text-red">S: $${formatCurrency(sw)}</span>`;
                        
                        // Add liquidity levels
                        if (coin.bounce_at && coin.reject_at) {
                            wallHtml += `<br><small class="text-muted">Bounce: $${coin.bounce_at < 1 ? coin.bounce_at.toFixed(4) : coin.bounce_at.toFixed(2)} | Reject: $${coin.reject_at < 1 ? coin.reject_at.toFixed(4) : coin.reject_at.toFixed(2)}</small>`;
                        }
                    }
                    
                    let predHtml = `<span class="text-muted">Neutral</span>`;
                    if (coin.ai_pred && coin.ai_pred.dir !== 'NEUTRAL') {
                        const isUp = coin.ai_pred.dir === 'UP';
                        const colorClass = isUp ? 'text-green' : 'text-red';
                        const arrow = isUp ? '↑' : '↓';
                        const prob = coin.ai_pred.prob;
                        const exp = coin.ai_pred.exp;
                        
                        let badge = '';
                        if (prob >= 80) badge = isUp ? '🔥 STRONG BUY ' : '🚨 STRONG SELL ';
                        
                        let tgtHtml = '';
                        if (coin.ai_pred.target) {
                            tgtHtml = `<br><span class="text-muted" style="font-size:0.85rem">${coin.ai_pred.target}</span>`;
                        }
                        
                        predHtml = `<strong class="${colorClass}">${badge}${prob}% ${arrow}</strong><br><small class="text-muted">Exp: ${exp}</small>${tgtHtml}`;
                        
                        // Update latest alert if strong signal
                        if (prob >= 80) {
                            if (!previousData[coin.symbol] || !previousData[coin.symbol].ai_pred || previousData[coin.symbol].ai_pred.prob < 80) {
                                document.getElementById('latest-alert').innerHTML = `<span class="${colorClass}">${badge} ${coin.symbol} (${prob}% ${arrow})</span>`;
                            }
                        }
                    }

                    try {
                        let alertHtml = '';
                        let timeStr = '';
                        if (stickyAlerts[coin.symbol] && stickyAlerts[coin.symbol].timestamp) {
                            const d = new Date(stickyAlerts[coin.symbol].timestamp);
                            timeStr = ` <small style="opacity:0.7; font-size:0.75rem; margin-left:4px;">[${d.toLocaleTimeString('en-US', { timeZone: 'Asia/Kolkata', hour12: true, hour: '2-digit', minute:'2-digit', second:'2-digit' })}]</small>`;
                        }

                        if (coin.warning === 'FAKE_PUMP') alertHtml = `<span class="alert-dump" style="background: rgba(239, 68, 68, 0.2); border: 1px solid #ef4444; color: #ef4444;"><i class="fa-solid fa-triangle-exclamation"></i> FAKE PUMP${timeStr}</span>`;
                        else if (coin.warning === 'FAKE_DUMP') alertHtml = `<span class="alert-pump" style="background: rgba(34, 197, 94, 0.2); border: 1px solid #22c55e; color: #22c55e;"><i class="fa-solid fa-triangle-exclamation"></i> FAKE DUMP${timeStr}</span>`;
                        else if (coin.alert === 'BREAKOUT') alertHtml = `<span class="alert-pump" style="background: rgba(168, 85, 247, 0.2); border: 1px solid #a855f7; color: #a855f7;"><i class="fa-solid fa-rocket"></i> 10x BREAKOUT${timeStr}</span>`;
                        else if (coin.alert === 'PUMP') alertHtml = `<span class="alert-pump">🔥 PUMP${timeStr}</span>`;
                        else if (coin.alert === 'DUMP') alertHtml = `<span class="alert-dump">🩸 DUMP${timeStr}</span>`;
                        
                        tr.innerHTML = `
                            <td class="coin-cell">
                                <i class="fa-brands fa-bitcoin text-muted"></i>
                                <a href="/analysis/${coin.symbol.replace('/', '_')}" target="_blank" style="color: inherit; text-decoration: none; border-bottom: 1px dashed var(--text-secondary);">${coin.symbol}</a>
                                ${alertHtml}
                            </td>
                            <td>${renderPrice(coin)}</td>
                            <td>${predHtml}</td>
                            <td id="wall-${coin.symbol.replace('/', '-')}">${wallHtml}</td>
                            <td class="${vol5mClass}">${formatVol(coin, 'buy_vol_5m', 'sell_vol_5m')}</td>
                            <td>${formatVol(coin, 'buy_vol_15m', 'sell_vol_15m')}</td>
                            <td>${formatVol(coin, 'buy_vol_1h', 'sell_vol_1h')}</td>
                            <td>${formatVol(coin, 'buy_vol_4h', 'sell_vol_4h')}</td>
                            <td>${formatVol(coin, 'buy_vol_24h', 'sell_vol_24h')}</td>
                        `;
                        tbody.appendChild(tr);
                    } catch (e) {
                        console.error("Error rendering coin:", coin.symbol, e);
                    }
                });
                
                // Save data for next flash check AFTER rendering
                cachedData.forEach(coin => {
                    previousData[coin.symbol] = coin;
                });
                
                document.getElementById('total-coins').textContent = visibleCount;
                
                if (topGainer && visibleCount > 0) {
                    document.getElementById('top-gainer').textContent = topGainer.symbol;
                    document.getElementById('top-gainer-vol').innerHTML = `<span class="text-green">Buy: +$${formatCurrency(topGainer.buy_vol_5m)}</span>`;
                } else {
                    document.getElementById('top-gainer').textContent = '-';
                    document.getElementById('top-gainer-vol').textContent = '0 USDT';
                }
            }
        })
        .catch(err => console.error("Error fetching data:", err));
}

// Fetch Wall on demand
window.fetchWall = function(symbol) {
    const td = document.getElementById(`wall-${symbol.replace('/', '-')}`);
    if (td) td.innerHTML = '<span class="text-muted"><i class="fa-solid fa-spinner fa-spin"></i> Fetching...</span>';
    
    fetch(`/api/depth?symbol=${encodeURIComponent(symbol)}`)
        .then(res => res.json())
        .then(data => {
            if (data.status === 'success') {
                updateDashboard(); // Will re-render with the newly cached wall
            } else {
                if (td) td.innerHTML = `<span class="text-red">Error</span>`;
            }
        });
};

// Search listener
document.getElementById('search-input').addEventListener('input', updateDashboard);

// Filter listeners
document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        e.target.classList.add('active');
        currentFilter = e.target.getAttribute('data-filter');
        updateDashboard();
    });
});

// Update every 10 seconds (Dashboard)
setInterval(updateDashboard, 10000);

// Initial call
updateDashboard();
