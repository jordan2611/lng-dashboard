import streamlit as st
import yfinance as yf
import requests
import feedparser
import google.generativeai as genai
import streamlit.components.v1 as components
from datetime import datetime, timedelta, timezone
from time import mktime

# --- 页面配置 ---
st.set_page_config(page_title="LNG Trading Desk V6.0", layout="wide", page_icon="🚢")

# --- CSS ---
st.markdown("""
    <style>
    .stMetric {background-color: #f8f9fa; padding: 10px; border-radius: 8px; border: 1px solid #e9ecef;}
    /* 模拟 Bloomberg 终端风格的表格 */
    table {width: 100%; border-collapse: collapse; font-family: 'Courier New', monospace;}
    th {background-color: #333; color: white; text-align: left; padding: 8px;}
    td {border-bottom: 1px solid #ddd; padding: 8px; font-size: 14px;}
    a {text-decoration: none; font-weight: bold; color: #0068c9;}
    </style>
    """, unsafe_allow_html=True)

# --- 侧边栏 ---
st.sidebar.title("⚡ LNG Pro V6.0")
st.sidebar.caption("Year-on-Year Storage & Port Radar")

with st.sidebar.expander("🔑 API Keys", expanded=True):
    gemini_key = st.sidebar.text_input("Gemini Key", type="password")
    eia_key = st.sidebar.text_input("EIA Key (US)", type="password")
    gie_key = st.sidebar.text_input("GIE Key (EU)", type="password")

with st.sidebar.expander("⚙️ Calc Settings", expanded=False):
    freight_cost = st.sidebar.slider("Freight ($/MMBtu)", 0.2, 3.0, 0.8)
    liquefaction_cost = st.sidebar.number_input("Liq Cost", value=3.0)

manual_ttf = st.sidebar.number_input("Manual TTF (€/MWh)", value=0.0)

# --- 核心函数 ---

def get_market_data():
    tickers = {"HH": "NG=F", "TTF": "TTF=F", "JKM": "JKM=F", "Oil": "BZ=F"}
    data = {}
    for name, ticker in tickers.items():
        try:
            hist = yf.Ticker(ticker).history(period="5d")
            if not hist.empty:
                current = hist['Close'].iloc[-1]
                prev = hist['Close'].iloc[-2]
                change = current - prev
                data[name] = {"price": current, "change": change, "valid": True}
            else:
                data[name] = {"price": 0, "change": 0, "valid": False}
        except:
            data[name] = {"price": 0, "change": 0, "valid": False}
    
    if (not data["TTF"]["valid"] or data["TTF"]["price"] < 1) and manual_ttf > 0:
        data["TTF"] = {"price": manual_ttf, "change": 0, "valid": True, "source": "Manual"}
    return data

# --- EIA 库存 (加入同比逻辑) ---
def get_eia_storage_analysis(api_key):
    if not api_key: return None, "No Key"
    try:
        url = "https://api.eia.gov/v2/natural-gas/stor/wkly/data/"
        # 我们获取过去 60 条数据 (约1年多)，以便找到去年同期
        params = {
            'api_key': api_key, 'frequency': 'weekly', 'data[0]': 'value',
            'facets[series][]': 'NW2_EPG0_SWO_R48_BCF', 
            'sort[0][column]': 'period', 'sort[0][direction]': 'desc', 'length': 60
        }
        r = requests.get(url, params=params, timeout=5).json()
        d = r.get('response', {}).get('data', []) or r.get('data', [])
        
        if len(d) < 53: return None, "Not enough history"
        
        current_week = d[0]
        last_year_week = d[52] # 大约52周前
        
        curr_val = float(current_week['value'])
        last_year_val = float(last_year_week['value'])
        
        # 计算同比差值 (Year-on-Year Surplus/Deficit)
        yoy_diff = curr_val - last_year_val
        yoy_pct = (yoy_diff / last_year_val) * 100
        
        weekly_change = float(d[0]['value']) - float(d[1]['value'])
        
        return {
            "val": curr_val, 
            "chg": weekly_change, 
            "date": current_week['period'],
            "yoy_diff": yoy_diff,
            "yoy_pct": yoy_pct,
            "last_year_val": last_year_val
        }, "OK"
    except Exception as e:
        return None, str(e)

# --- GIE 库存 (加入同比逻辑) ---
def get_gie_storage_analysis(api_key):
    if not api_key: return None, "No Key"
    try:
        # GIE API 支持直接查历史，我们查一下最新的
        url = "https://agsi.gie.eu/api"
        headers = {"x-key": api_key}
        
        # 1. 获取最新数据
        r_curr = requests.get(url, headers=headers, params={'type': 'eu'}, timeout=5).json()
        d_curr = r_curr['data'][0]
        
        # 2. 获取去年同期数据 (计算日期)
        curr_date = datetime.strptime(d_curr['gasDayStart'], "%Y-%m-%d")
        last_year_date = curr_date - timedelta(days=365)
        date_str = last_year_date.strftime("%Y-%m-%d")
        
        r_hist = requests.get(url, headers=headers, params={'type': 'eu', 'date': date_str}, timeout=5).json()
        d_hist = r_hist['data'][0]
        
        curr_full = float(d_curr['full'])
        last_full = float(d_hist['full'])
        diff = curr_full - last_full
        
        return {
            "full": curr_full, 
            "val": float(d_curr['gasInStorage']), 
            "date": d_curr['gasDayStart'],
            "yoy_diff": diff, # 同比填充率差值
            "last_year_full": last_full
        }, "OK"
    except Exception as e:
        return None, str(e)

def fetch_news_headlines():
    # ... (保持 V5.5 的代码不变，为了节省篇幅，这里复用之前的逻辑) ...
    # 请确保这里有 V5.5 的 fetch_news_headlines 代码
    headers = {"User-Agent": "Mozilla/5.0"}
    sources = [("LNG Prime", "https://lngprime.com/feed/"), ("Reuters Energy", "http://feeds.reuters.com/reuters/energyNews")]
    news_items = []
    log = []
    for name, url in sources:
        try:
            d = feedparser.parse(url)
            for e in d.entries[:2]:
                news_items.append({"title": e.title, "link": e.link, "source": name, "time_str": "Today"})
        except: pass
    return news_items, log

def get_working_model(api_key):
    genai.configure(api_key=api_key)
    return "models/gemini-pro"

# --- 主界面 ---

st.title("🚢 Global LNG Trading Desk V6.0")

# 1. Fundamentals (深度升级：同比分析)
st.subheader("1. Inventory Context (vs Last Year)")
c1, c2 = st.columns(2)

eia_data, eia_msg = get_eia_storage_analysis(eia_key)
gie_data, gie_msg = get_gie_storage_analysis(gie_key)

with c1:
    if eia_data:
        st.metric("🇺🇸 US Storage", f"{eia_data['val']:.0f} Bcf", f"{eia_data['chg']:.0f} Bcf (WoW)")
        
        # 同比分析展示
        diff_color = "green" if eia_data['yoy_diff'] > 0 else "red" 
        st.markdown(f"""
        <div style="background-color: #eee; padding: 10px; border-radius: 5px; font-size: 0.9em;">
        <b>Year-on-Year:</b> <span style="color:{diff_color}">{eia_data['yoy_diff']:.0f} Bcf ({eia_data['yoy_pct']:.1f}%)</span> vs Last Year<br>
        <span style="color: grey; font-size: 0.8em;">(Last Year: {eia_data['last_year_val']:.0f} Bcf)</span>
        </div>
        """, unsafe_allow_html=True)
        
        # 简单解读
        if eia_data['yoy_diff'] > 0:
            st.caption("📉 Bearish: Inventory is HIGHER than last year.")
        else:
            st.caption("📈 Bullish: Inventory is TIGHTER than last year.")
            
    else:
        st.metric("🇺🇸 US Storage", "N/A", eia_msg)

with c2:
    if gie_data:
        st.metric("🇪🇺 EU Storage", f"{gie_data['full']:.2f}% Full", f"{gie_data['val']:.1f} TWh")
        
        diff_color = "green" if gie_data['yoy_diff'] > 0 else "red"
        st.markdown(f"""
        <div style="background-color: #eee; padding: 10px; border-radius: 5px; font-size: 0.9em;">
        <b>YoY Comparison:</b> <span style="color:{diff_color}">{gie_data['yoy_diff']:.2f}%</span> vs Last Year<br>
        <span style="color: grey; font-size: 0.8em;">(Last Year: {gie_data['last_year_full']:.2f}%)</span>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.metric("🇪🇺 EU Storage", "N/A", gie_msg)

st.divider()

# 2. Port Radar (MarineTraffic/VesselFinder 替代方案)
st.subheader("2. Strategic Port Radar (Live Ships)")
st.caption("Real-time vessel tracking at key Chokepoints (No Subscription Needed)")

# 港口选择器
port_option = st.selectbox("Select Key Hub:", ["🇺🇸 Sabine Pass (US Export)", "🇳🇱 Rotterdam (EU Import)", "🇯🇵 Tokyo Bay (Asia Import)"])

# VesselFinder 免费嵌入代码 (根据坐标)
# Sabine Pass: 29.74, -93.87
# Rotterdam: 51.95, 4.05
# Tokyo: 35.5, 139.8
if "Sabine" in port_option:
    coords = {"lat": 29.74, "lon": -93.87, "zoom": 10}
elif "Rotterdam" in port_option:
    coords = {"lat": 51.95, "lon": 4.05, "zoom": 9}
else:
    coords = {"lat": 35.5, "lon": 139.8, "zoom": 9}

# 嵌入 VesselFinder Map Widget
# 注意：这比 MarineTraffic 的免费版更干净
html_map = f"""
<iframe name="vesselfinder" id="vesselfinder" 
src="https://www.vesselfinder.com/aismap?zoom={coords['zoom']}&lat={coords['lat']}&lon={coords['lon']}&width=100%&height=400&names=true&mmsi=0&imo=0&sc_0=1&sc_1=1&sc_2=0&sc_3=0&sc_4=0&sc_5=1&sc_6=0&sc_7=0" 
width="100%" height="400" frameborder="0">Browser does not support iframes.</iframe>
"""
components.html(html_map, height=400)
st.caption("💡 Tip: Look for large Green/Red icons. LNG tankers often have names like 'Maran Gas', 'Al Ghashamiya', 'LNG Enterprise'.")

st.divider()

# 3. Prices & Arb
# ... (保留 V5.5 的价格和套利逻辑) ...
prices = get_market_data()
k1, k2, k3, k4 = st.columns(4)
k1.metric("Henry Hub", f"${prices['HH']['price']:.2f}", f"{prices['HH']['change']:.2f}")
k2.metric("TTF (EU)", f"€{prices['TTF']['price']:.2f}", f"{prices['TTF']['change']:.2f}")
# ... 其他价格 ...

# 4. AI Analysis
# ... (保留 V5.5 的 AI 逻辑) ...
st.subheader("4. AI Analyst")
# ...
