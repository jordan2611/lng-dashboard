import streamlit as st
import yfinance as yf
import feedparser
import google.generativeai as genai
import pandas as pd
import plotly.graph_objects as go
import requests
from datetime import datetime
from time import mktime

# ==========================================
# 0. 全局配置 & 样式
# ==========================================
st.set_page_config(
    page_title="LNG Trading Dashboard V4 Pro",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 估算参数
TTF_CONVERSION_FACTOR = 0.31  # EUR/MWh -> USD/MMBtu
ARB_COST_ESTIMATE = 8.0       # USD/MMBtu

st.markdown("""
    <style>
    .metric-container {
        background-color: #ffffff;
        padding: 12px;
        border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        border: 1px solid #f0f0f0;
        text-align: center;
    }
    .metric-label { font-size: 0.85em; color: #666; font-weight: 500; text-transform: uppercase; }
    .metric-value { font-size: 1.5em; font-weight: 700; color: #333; margin: 5px 0; }
    .metric-sub { font-size: 0.8em; color: #888; }
    
    .storage-card {
        background-color: #f8f9fa;
        border-left: 4px solid #1f77b4;
        padding: 15px;
        border-radius: 5px;
    }
    .arb-box-open {
        background-color: #d4edda; border: 1px solid #c3e6cb; color: #155724;
        padding: 10px; border-radius: 8px; text-align: center; font-weight: bold;
    }
    .arb-box-closed {
        background-color: #f8d7da; border: 1px solid #f5c6cb; color: #721c24;
        padding: 10px; border-radius: 8px; text-align: center; font-weight: bold;
    }
    .news-item { border-bottom: 1px solid #eee; padding: 8px 0; font-size: 0.9em; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 1. Sidebar: Configuration
# ==========================================
st.sidebar.title("⚡ LNG Pro V4.0")
st.sidebar.markdown("Professional Trading Desk")

# --- API Keys ---
st.sidebar.subheader("🔑 API Configuration")
with st.sidebar.expander("API Keys Setup", expanded=True):
    google_key = st.text_input("Google Gemini Key", type="password")
    eia_key = st.text_input("EIA API Key (US Storage)", type="password", help="Get free key at eia.gov/opendata")
    gie_key = st.text_input("GIE API Key (EU Storage)", type="password", help="Get key at agsi.gie.eu")

# --- AI Init ---
ai_enabled = False
if google_key:
    try:
        genai.configure(api_key=google_key)
        ai_enabled = True
    except: pass

st.sidebar.markdown("---")
st.sidebar.info("Data Sources:\n- Prices: Yahoo Finance\n- Storage: EIA (US) & AGSI (EU)\n- News: Reuters/OilPrice")

# ==========================================
# 2. Data Functions (Prices, Storage, News)
# ==========================================

# --- 2.1 Market Prices ---
@st.cache_data(ttl=300)
def get_market_data():
    tickers = ['NG=F', 'TTF=F', 'JKM=F', 'BZ=F']
    try:
        data = yf.download(tickers, period="1mo", group_by='ticker', progress=False)
        res = {}
        def get_s(s): return data[s]['Close'].dropna() if s in data and not data[s]['Close'].dropna().empty else None
        res['HH'], res['TTF'] = get_s('NG=F'), get_s('TTF=F')
        res['JKM'], res['BRENT'] = get_s('JKM=F'), get_s('BZ=F')
        return res
    except: return {}

# --- 2.2 EIA Storage (US) ---
@st.cache_data(ttl=3600) # 缓存1小时
def get_eia_storage(api_key):
    if not api_key: return None
    url = "https://api.eia.gov/v2/natural-gas/stor/wkly/data/"
    params = {
        'api_key': api_key,
        'frequency': 'weekly',
        'data[0]': 'value',
        'facets[series][]': 'NW2_EPG0_SWO_R48_BCF', # Lower 48 Total
        'sort[0][column]': 'period',
        'sort[0][direction]': 'desc',
        'offset': 0,
        'length': 5
    }
    try:
        r = requests.get(url, params=params)
        data = r.json()['response']['data']
        # data[0] is latest, data[1] is previous
        latest = float(data[0]['value'])
        prev = float(data[1]['value'])
        date = data[0]['period']
        return {"val": latest, "delta": latest - prev, "date": date}
    except Exception as e:
        return {"error": str(e)}

# --- 2.3 GIE Storage (EU) ---
@st.cache_data(ttl=3600)
def get_gie_storage(api_key):
    if not api_key: return None
    url = "https://agsi.gie.eu/api"
    headers = {"x-key": api_key}
    params = {'type': 'eu'} # EU Aggregate
    try:
        r = requests.get(url, headers=headers, params=params)
        data = r.json()['data'][0] # Latest day
        return {
            "full": float(data['full']),
            "twh": float(data['gasInStorage']),
            "date": data['gasDayStart']
        }
    except Exception as e:
        return {"error": str(e)}

# --- 2.4 Arbitrage Calc ---
def calculate_arbitrage(hh, ttf):
    if hh is None or ttf is None: return None, 0, False
    df = pd.DataFrame({'HH': hh, 'TTF': ttf}).dropna()
    if df.empty: return None, 0, False
    df['Spread'] = (df['TTF'] * TTF_CONVERSION_FACTOR) - df['HH']
    last = df['Spread'].iloc[-1]
    return df, last, last > ARB_COST_ESTIMATE

# --- 2.5 News RSS ---
@st.cache_data(ttl=600)
def get_news():
    sources = [
        ("Reuters", "http://feeds.reuters.com/reuters/energyNews"),
        ("OilPrice", "https://oilprice.com/rss/main"),
        ("LNG Prime", "https://lngprime.com/feed/")
    ]
    news = []
    for src, url in sources:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:3]:
                dt = datetime.now()
                if hasattr(e, 'published_parsed') and e.published_parsed:
                    dt = datetime.fromtimestamp(mktime(e.published_parsed))
                news.append({"src": src, "title": e.title, "link": e.link, "dt": dt})
        except: continue
    return sorted(news, key=lambda x: x['dt'], reverse=True)[:6]

# ==========================================
# 3. Main Dashboard Layout
# ==========================================
st.title("🚢 LNG Trading Dashboard V4.0 Pro")
st.markdown("Real-time Pricing, Storage Fundamental & Arb Signals")

# --- ROW 1: Global Storage Monitor (New) ---
st.subheader("1. Global Storage Monitor (Fundamentals)")
sc1, sc2 = st.columns(2)

# US Storage
with sc1:
    if eia_key:
        eia_data = get_eia_storage(eia_key)
        if eia_data and "error" not in eia_data:
            delta_symbol = "▲" if eia_data['delta'] >= 0 else "▼"
            delta_color = "red" if eia_data['delta'] < 0 else "green" # draw is bullish(red?), build is bearish? standard green/red used here
            st.markdown(f"""
            <div class="storage-card">
                <h4>🇺🇸 US Storage (EIA Lower 48)</h4>
                <div style="font-size: 2em; font-weight: bold;">{eia_data['val']} <span style="font-size:0.5em">Bcf</span></div>
                <div style="color: {delta_color}">
                    {delta_symbol} {eia_data['delta']:.1f} Bcf vs prev week
                </div>
                <div style="font-size: 0.8em; color: gray; margin-top: 5px;">Period: {eia_data['date']}</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.error(f"EIA Error: {eia_data.get('error')}" if eia_data else "Failed to fetch")
    else:
        st.info("Waiting for EIA API Key... (Sidebar)")

# EU Storage
with sc2:
    if gie_key:
        gie_data = get_gie_storage(gie_key)
        if gie_data and "error" not in gie_data:
            # Color scale for fullness
            full_color = "#28a745" if gie_data['full'] > 90 else "#ffc107"
            st.markdown(f"""
            <div class="storage-card" style="border-left-color: #ffc107;">
                <h4>🇪🇺 EU Storage (GIE Aggregate)</h4>
                <div style="font-size: 2em; font-weight: bold; color: {full_color};">
                    {gie_data['full']:.2f}% <span style="font-size:0.5em; color:black">Full</span>
                </div>
                <div>Volume: <b>{gie_data['twh']:.1f}</b> TWh</div>
                <div style="font-size: 0.8em; color: gray; margin-top: 5px;">Date: {gie_data['date']}</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.error(f"GIE Error: {gie_data.get('error')}" if gie_data else "Failed to fetch")
    else:
        st.info("Waiting for GIE API Key... (Sidebar)")

st.markdown("---")

# --- ROW 2: Price Matrix ---
st.subheader("2. Market Prices & Macro")
prices = get_market_data()
pc1, pc2, pc3, pc4 = st.columns(4)

def show_price(col, name, s, curr_sign):
    with col:
        if s is not None:
            cur = s.iloc[-1]
            chg = cur - (s.iloc[-2] if len(s)>1 else cur)
            clr = "green" if chg>=0 else "red"
            st.markdown(f"""
            <div class="metric-container">
                <div class="metric-label">{name}</div>
                <div class="metric-value">{curr_sign}{cur:.2f}</div>
                <div class="metric-sub" style="color:{clr}">{chg:+.2f}</div>
            </div>""", unsafe_allow_html=True)
        else:
            st.warning(f"{name}: No Data")

show_price(pc1, "Henry Hub", prices.get('HH'), "$")
show_price(pc2, "Dutch TTF", prices.get('TTF'), "€")
show_price(pc3, "JKM (Asia)", prices.get('JKM'), "$")
show_price(pc4, "Brent Oil", prices.get('BRENT'), "$")

st.markdown("---")

# --- ROW 3: Arbitrage Monitor ---
st.subheader("3. US-EU Arbitrage Monitor")
arb_df, arb_val, arb_open = calculate_arbitrage(prices.get('HH'), prices.get('TTF'))

ac1, ac2 = st.columns([1, 3])
with ac1:
    st.markdown("<br>", unsafe_allow_html=True)
    if arb_open:
        st.markdown(f"""
        <div class="arb-box-open">
            ✅ WINDOW OPEN<br>
            Spread: ${arb_val:.2f}
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="arb-box-closed">
            ❌ WINDOW CLOSED<br>
            Spread: ${arb_val:.2f}
        </div>""", unsafe_allow_html=True)
    
    st.caption(f"Cost Basis: ${ARB_COST_ESTIMATE}/MMBtu")
    
    if ai_enabled and arb_df is not None:
        if st.button("AI Strategy"):
            with st.spinner("Analyzing..."):
                prompt = f"Spread is ${arb_val:.2f}, Trend is {'Up' if arb_val > arb_df['Spread'].mean() else 'Down'}. Storage levels visible above. Advice for trader?"
                model = genai.GenerativeModel('gemini-pro')
                res = model.generate_content(prompt)
                st.info(res.text)

with ac2:
    if arb_df is not None:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=arb_df.index, y=arb_df['Spread'], fill='tozeroy', name='Net Spread', line=dict(color='#1f77b4')))
        fig.add_trace(go.Scatter(x=[arb_df.index[0], arb_df.index[-1]], y=[ARB_COST_ESTIMATE, ARB_COST_ESTIMATE], mode='lines', name='Cost', line=dict(dash='dash', color='orange')))
        fig.update_layout(height=300, margin=dict(t=20, b=20, l=40, r=20), title="Spread vs Cost ($/MMBtu)")
        st.plotly_chart(fig, use_container_width=True)

# --- ROW 4: Intelligence ---
st.subheader("4. Market Intelligence")
news = get_news()
nc1, nc2 = st.columns(2)
for i, n in enumerate(news):
    with (nc1 if i%2==0 else nc2):
        st.markdown(f"""
        <div class="news-item">
            <b>{n['src']}</b> <span style="color:#888">| {n['dt'].strftime('%H:%M')}</span><br>
            <a href="{n['link']}" target="_blank">{n['title']}</a>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<br><div style='text-align:center;color:#aaa'>LNG Dashboard V4.0 Pro | Built with Python Streamlit</div>", unsafe_allow_html=True)
