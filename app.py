import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import feedparser
from datetime import datetime, timedelta
import google.generativeai as genai

# --- 页面配置 ---
st.set_page_config(page_title="LNG Trading Desk V4.5", layout="wide", page_icon="🚢")

# --- 侧边栏配置 ---
st.sidebar.title("⚡ LNG Pro V4.5")
st.sidebar.caption("Professional Trading Desk")

# API Keys
with st.sidebar.expander("🔑 API Keys Setup", expanded=True):
    gemini_key = st.sidebar.text_input("Google Gemini Key", type="password")
    eia_key = st.sidebar.text_input("EIA API Key (US Storage)", type="password")
    gie_key = st.sidebar.text_input("GIE API Key (EU Storage)", type="password")

# 参数设置
with st.sidebar.expander("⚙️ Arbitrage Settings", expanded=True):
    freight_cost = st.sidebar.slider("Freight Cost ($/MMBtu)", 0.2, 3.0, 0.8, 0.1)
    liquefaction_cost = st.sidebar.number_input("Liquefaction/Toll ($/MMBtu)", value=3.0)
    
# TTF 手动修正
st.sidebar.markdown("---")
manual_ttf = st.sidebar.number_input("Manual TTF Price (€/MWh)", value=0.0, help="如果自动获取失败，请在此手动输入")

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
                data[name] = {"price": current, "change": change, "status": "Live"}
            else:
                data[name] = {"price": None, "change": 0, "status": "No Data"}
        except Exception as e:
            data[name] = {"price": None, "change": 0, "status": "Error"}
            
    # TTF 兜底逻辑
    if (data["TTF"]["price"] is None or data["TTF"]["price"] == 0) and manual_ttf > 0:
        data["TTF"] = {"price": manual_ttf, "change": 0, "status": "Manual"}
        
    return data

def get_eia_storage(api_key):
    if not api_key:
        return None, "Key Required"
    
    url = "https://api.eia.gov/v2/natural-gas/stor/wkly/data/"
    params = {
        'api_key': api_key,
        'frequency': 'weekly',
        'data[0]': 'value',
        'facets[series][]': 'NW2_EPG0_SWO_R48_BCF',
        'sort[0][column]': 'period',
        'sort[0][direction]': 'desc',
        'offset': 0,
        'length': 2
    }
    
    try:
        r = requests.get(url, params=params)
        data = r.json()
        # 修复报错的关键：更安全的解析路径
        if 'response' in data:
            series_data = data['response']['data']
        elif 'data' in data: # 有时候EIA直接返回data
            series_data = data['data']
        else:
            return None, "Parse Error"

        current = float(series_data[0]['value'])
        prev = float(series_data[1]['value'])
        change = current - prev
        date = series_data[0]['period']
        return {"current": current, "change": change, "date": date}, "OK"
    except Exception as e:
        return None, str(e)

def get_gie_storage(api_key):
    if not api_key:
        return None, "Key Required"
    
    url = "https://agsi.gie.eu/api"
    headers = {"x-key": api_key}
    params = {'type': 'eu'}
    
    try:
        r = requests.get(url, headers=headers, params=params)
        data = r.json()
        latest = data['data'][0]
        return {
            "full": float(latest['full']),
            "volume": float(latest['gasInStorage']),
            "date": latest['gasDayStart']
        }, "OK"
    except Exception as e:
        return None, str(e)

def get_weather():
    # 使用 Open-Meteo 免费 API (无需 Key)
    # Amsterdam (52.36, 4.90), Sabine Pass (29.73, -93.89)
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": [52.36, 29.73, 35.68], # AMS, Sabine, Tokyo
        "longitude": [4.90, -93.89, 139.65],
        "daily": "temperature_2m_max",
        "timezone": "auto",
        "forecast_days": 3
    }
    try:
        r = requests.get(url, params=params)
        data = r.json()
        
        # 简单解析未来3天平均最高温
        ams_temp = sum(data[0]['daily']['temperature_2m_max']) / 3
        us_temp = sum(data[1]['daily']['temperature_2m_max']) / 3
        tokyo_temp = sum(data[2]['daily']['temperature_2m_max']) / 3
        
        return {"EU": ams_temp, "US": us_temp, "Asia": tokyo_temp}
    except:
        return {"EU": 0, "US": 0, "Asia": 0}

# --- 主界面 ---

st.title("🚢 Global LNG Trading Dashboard V4.5")
st.markdown("Real-time Intelligence & Arbitrage Monitor")

# 1. 库存与基本面
st.subheader("1. Global Fundamentals (Storage & Weather)")
col_s1, col_s2, col_s3 = st.columns(3)

# EIA
storage_us, status_us = get_eia_storage(eia_key)
with col_s1:
    if storage_us:
        st.metric("🇺🇸 US Storage (EIA)", f"{storage_us['current']} Bcf", f"{storage_us['change']:.1f} Bcf")
        st.caption(f"Date: {storage_us['date']}")
    else:
        st.warning(f"US Data: {status_us}")

# GIE
storage_eu, status_eu = get_gie_storage(gie_key)
with col_s2:
    if storage_eu:
        st.metric("🇪🇺 EU Storage (GIE)", f"{storage_eu['full']:.2f}% Full", f"{storage_eu['volume']:.1f} TWh")
        st.caption(f"Date: {storage_eu['date']}")
    else:
        st.warning(f"EU Data: {status_eu}")

# Weather
weather = get_weather()
with col_s3:
    st.markdown("**🌡️ 3-Day Avg Temp**")
    c1, c2, c3 = st.columns(3)
    c1.metric("Amsterdam", f"{weather['EU']:.1f}°C")
    c2.metric("Sabine Pass", f"{weather['US']:.1f}°C")
    c3.metric("Tokyo", f"{weather['Asia']:.1f}°C")

st.divider()

# 2. 市场价格
st.subheader("2. Market Prices & Macro")
prices = get_market_data()
col1, col2, col3, col4 = st.columns(4)

with col1:
    p = prices["HH"]
    st.metric("Henry Hub (US)", f"${p['price']:.3f}" if p['price'] else "N/A", f"{p['change']:.3f}" if p['price'] else None)

with col2:
    p = prices["TTF"]
    val = f"€{p['price']:.3f}" if p['price'] else "No Data"
    delta = f"{p['change']:.3f}" if p['price'] else None
    st.metric("Dutch TTF (EU)", val, delta, delta_color="normal" if p['status']=="Manual" else "normal")
    if p['status'] == "Manual":
        st.caption("⚠️ Manual Input")
    elif p['status'] == "No Data":
        st.caption("❌ Yahoo API Failed - Use Sidebar")

with col3:
    p = prices["JKM"]
    st.metric("JKM (Asia)", f"${p['price']:.3f}" if p['price'] else "N/A", f"{p['change']:.3f}" if p['price'] else None)

with col4:
    p = prices["Oil"]
    st.metric("Brent Oil", f"${p['price']:.2f}" if p['price'] else "N/A", f"{p['change']:.2f}" if p['price'] else None)

st.divider()

# 3. 套利监视器
st.subheader("3. US-EU Arbitrage Monitor")

if prices["HH"]["price"] and prices["TTF"]["price"]:
    hh_price = prices["HH"]["price"]
    ttf_price_eur = prices["TTF"]["price"]
    
    # 简单的单位换算: 1 MWh approx 3.412 MMBtu, 汇率假设 EUR/USD = 1.05 (你可以写死或抓取)
    fx_rate = 1.05
    ttf_price_usd_mmbtu = (ttf_price_eur * fx_rate) / 3.412
    
    # 公式: Profit = (Sales - Discount) - (Cost + Toll + Freight)
    sales_price = ttf_price_usd_mmbtu - 1.0 # DES discount
    cost_price = (1.15 * hh_price) + liquefaction_cost + freight_cost
    
    spread = sales_price - cost_price
    
    c_arb1, c_arb2 = st.columns([1, 2])
    
    with c_arb1:
        if spread > 0:
            st.success(f"✅ ARB OPEN: ${spread:.2f}/MMBtu")
        else:
            st.error(f"❌ ARB CLOSED: ${spread:.2f}/MMBtu")
        
        st.info(f"""
        **Calculation:**
        TTF ($): {ttf_price_usd_mmbtu:.2f}
        - Cost: {cost_price:.2f}
        (HH*1.15 + {liquefaction_cost} + {freight_cost})
        """)
        
    with c_arb2:
        # 这里应该画图，简化起见先展示数据
        st.bar_chart({"Netback Profit": spread})

else:
    st.warning("Waiting for Price Data (Check HH and TTF)")

st.divider()

# 4. AI 智能情报
st.subheader("4. AI Intelligence (Gemini)")

rss_urls = [
    "http://feeds.reuters.com/reuters/energyNews",
    "https://oilprice.com/rss/main",
    "https://lngprime.com/feed/"
]

if st.button("🔄 Analyze Latest News"):
    if not gemini_key:
        st.error("Please enter Gemini API Key in Sidebar")
    else:
        news_items = []
        for url in rss_urls:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:2]:
                    news_items.append(f"- {entry.title}")
            except:
                pass
        
        if news_items:
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel('gemini-pro')
            
            prompt = f"""
            Act as a Senior LNG Trader. Analyze these news headlines and summarize the market sentiment in 3 bullet points. 
            Identify if there are any supply disruptions or demand spikes.
            
            Headlines:
            {"".join(news_items)}
            """
            
            with st.spinner("Gemini is reading the news..."):
                response = model.generate_content(prompt)
                st.markdown(response.text)
        else:
            st.write("No news found.")
