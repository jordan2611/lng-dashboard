import streamlit as st
import yfinance as yf
import requests
import feedparser
import google.generativeai as genai
import streamlit.components.v1 as components
from datetime import datetime
import pandas as pd # 引入pandas用来画表格

# --- 页面配置 ---
st.set_page_config(page_title="LNG Trading Desk V5.3", layout="wide", page_icon="🚢")

# --- 样式优化 ---
st.markdown("""
    <style>
    .stMetric {background-color: #f8f9fa; padding: 10px; border-radius: 8px; border: 1px solid #e9ecef;}
    </style>
    """, unsafe_allow_html=True)

# --- 侧边栏 ---
st.sidebar.title("⚡ LNG Pro V5.3")
st.sidebar.caption("Auto-Model Detect & Detailed Analysis")

with st.sidebar.expander("🔑 API Keys", expanded=True):
    gemini_key = st.sidebar.text_input("Gemini Key", type="password")
    eia_key = st.sidebar.text_input("EIA Key (US)", type="password")
    gie_key = st.sidebar.text_input("GIE Key (EU)", type="password")

with st.sidebar.expander("⚙️ Calc Settings", expanded=False):
    freight_cost = st.sidebar.slider("Freight ($/MMBtu)", 0.2, 3.0, 0.8)
    liquefaction_cost = st.sidebar.number_input("Liq Cost", value=3.0)

manual_ttf = st.sidebar.number_input("Manual TTF (€/MWh)", value=0.0)

# --- 核心功能函数 ---

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

def get_eia_storage(api_key):
    if not api_key: return None, "No Key"
    try:
        url = "https://api.eia.gov/v2/natural-gas/stor/wkly/data/"
        params = {
            'api_key': api_key, 'frequency': 'weekly', 'data[0]': 'value',
            'facets[series][]': 'NW2_EPG0_SWO_R48_BCF', 
            'sort[0][column]': 'period', 'sort[0][direction]': 'desc', 'length': 2
        }
        r = requests.get(url, params=params, timeout=5).json()
        d = r.get('response', {}).get('data', []) or r.get('data', [])
        if not d: return None, "Empty Data"
        return {"val": float(d[0]['value']), "chg": float(d[0]['value']) - float(d[1]['value']), "date": d[0]['period']}, "OK"
    except Exception as e:
        return None, str(e)

def get_gie_storage(api_key):
    if not api_key: return None, "No Key"
    try:
        r = requests.get("https://agsi.gie.eu/api", headers={"x-key": api_key}, params={'type': 'eu'}, timeout=5).json()
        d = r['data'][0]
        return {"full": float(d['full']), "val": float(d['gasInStorage']), "date": d['gasDayStart']}, "OK"
    except Exception as e:
        return None, str(e)

def fetch_news_headlines():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"}
    sources = [
        ("LNG Prime", "https://lngprime.com/feed/"),
        ("OilPrice", "https://oilprice.com/rss/main"),
        ("CNBC Energy", "https://www.cnbc.com/id/19836768/device/rss/rss.html"),
        ("Rigzone", "https://www.rigzone.com/news/rss/rigzone_latest.aspx"),
        ("Gas World", "https://www.gasworld.com/feed/"),
        ("Investing", "https://www.investing.com/rss/commodities.rss"),
        ("NatGasIntel", "https://www.naturalgasintel.com/feed/"),
    ]
    
    headlines = []
    log = []
    for name, url in sources:
        try:
            resp = requests.get(url, headers=headers, timeout=4)
            if resp.status_code == 200:
                feed = feedparser.parse(resp.content)
                for entry in feed.entries[:2]: # 只要前2条，避免太多
                    headlines.append(f"- [{name}] {entry.title}")
                log.append(f"✅ {name}")
            else:
                log.append(f"⚠️ {name} ({resp.status_code})")
        except:
            log.append(f"❌ {name}")
    return headlines, log

# --- 关键升级：自动寻找可用模型 ---
def get_working_model(api_key):
    genai.configure(api_key=api_key)
    try:
        # 列出所有模型
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        # 优先级排序：先找 Flash，再找 Pro，再找任意 Gemini
        for m in models:
            if 'flash' in m.lower(): return m
        for m in models:
            if 'pro' in m.lower(): return m
        for m in models:
            if 'gemini' in m.lower(): return m
            
        return "models/gemini-pro" # 最后的保底
    except:
        return "models/gemini-pro" # 如果列出失败，直接盲猜

# --- 主界面 ---

st.title("🚢 Global LNG Trading Desk V5.3")

# 1. Fundamentals
c1, c2 = st.columns(2)
eia_data, eia_msg = get_eia_storage(eia_key)
gie_data, gie_msg = get_gie_storage(gie_key)

with c1:
    if eia_data: st.metric("🇺🇸 US Storage (EIA)", f"{eia_data['val']:.0f} Bcf", f"{eia_data['chg']:.0f} Bcf")
    else: st.metric("🇺🇸 US Storage", "N/A", eia_msg)
with c2:
    if gie_data: st.metric("🇪🇺 EU Storage (GIE)", f"{gie_data['full']:.2f}%", f"{gie_data['val']:.1f} TWh")
    else: st.metric("🇪🇺 EU Storage", "N/A", gie_msg)

# 2. Price & Arb
st.divider()
prices = get_market_data()
k1, k2, k3, k4 = st.columns(4)
k1.metric("Henry Hub", f"${prices['HH']['price']:.2f}", f"{prices['HH']['change']:.2f}")
k2.metric("TTF (EU)", f"€{prices['TTF']['price']:.2f}", f"{prices['TTF']['change']:.2f}")
k3.metric("JKM (Asia)", f"${prices['JKM']['price']:.2f}", f"{prices['JKM']['change']:.2f}")
k4.metric("Brent Oil", f"${prices['Oil']['price']:.2f}", f"{prices['Oil']['change']:.2f}")

if prices['HH']['price'] > 0 and prices['TTF']['price'] > 0:
    hh = prices['HH']['price']
    ttf_usd = (prices['TTF']['price'] * 1.05) / 3.412
    cost = (hh * 1.15) + liquefaction_cost + freight_cost
    spread = (ttf_usd - 1.0) - cost
    if spread > 0: st.success(f"✅ ARB OPEN: Profit ${spread:.2f}/MMBtu")
    else: st.error(f"❌ ARB CLOSED: Loss ${spread:.2f}/MMBtu")

# 3. Weather
st.divider()
st.subheader("3. Live Weather (Windy)")
components.iframe(src="https://embed.windy.com/embed2.html?lat=40.0&lon=-50.0&zoom=3&level=surface&overlay=temp&product=ecmwf&menu=&message=&marker=&calendar=now&pressure=&type=map&location=coordinates&detail=&metricWind=default&metricTemp=default&radarRange=-1", height=450)

# 4. AI Analysis (逐条点评版)
st.divider()
st.subheader("4. AI Market Sentiment Scanner")

user_query = st.text_input("💬 Filter/Ask (e.g. 'Only show news about Strikes'):")

if st.button("🚀 Scan & Evaluate") or user_query:
    if not gemini_key:
        st.error("Need Gemini Key")
    else:
        with st.spinner("🕷️ Fetching News & Detecting AI Model..."):
            headlines, fetch_log = fetch_news_headlines()
            # 自动寻找可用模型
            model_name = get_working_model(gemini_key)
            st.caption(f"🤖 Using AI Model: `{model_name}`") # 让你看到到底用了哪个模型
        
        with st.expander("📡 Source Log"):
            st.write(fetch_log)
        
        if headlines:
            try:
                genai.configure(api_key=gemini_key)
                model = genai.GenerativeModel(model_name)
                
                # --- 核心升级：要求 AI 逐条点评 ---
                prompt = f"""
                You are a Senior LNG Trader. Review the following news headlines individually.
                
                Headlines:
                {chr(10).join(headlines)}
                
                Task:
                Create a markdown table with the following columns for EACH headline:
                1. **Headline**: Brief summary of the title.
                2. **Sentiment**: 'Bullish' (📈), 'Bearish' (📉), or 'Neutral' (➖).
                3. **Impact Score**: 1-10 (10 = massive price mover).
                4. **Trader's Take**: One short sentence on why.
                
                Finally, give a "Global Market Sentiment" summary at the bottom.
                
                User Context: {user_query if user_query else ""}
                """
                
                with st.spinner("🧠 Analyzing each headline..."):
                    response = model.generate_content(prompt)
                    st.markdown(response.text)
            except Exception as e:
                st.error(f"AI Error: {str(e)}")
                st.warning("Try generating a new API Key from Google AI Studio if 404 persists.")
        else:
            st.warning("No news fetched.")
