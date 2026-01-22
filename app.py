import streamlit as st
import yfinance as yf
import requests
import feedparser
import google.generativeai as genai
import streamlit.components.v1 as components # 用于嵌入天气地图

# --- 页面配置 ---
st.set_page_config(page_title="LNG Trading Desk V5.0", layout="wide", page_icon="🚢")

# --- CSS 样式优化 ---
st.markdown("""
    <style>
    .stMetric {
        background-color: #f0f2f6;
        padding: 10px;
        border-radius: 5px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 侧边栏 ---
st.sidebar.title("⚡ LNG Pro V5.0")
st.sidebar.caption("Live Intelligence & Arbitrage")

# Keys
with st.sidebar.expander("🔑 API Keys", expanded=True):
    gemini_key = st.sidebar.text_input("Gemini Key", type="password")
    eia_key = st.sidebar.text_input("EIA Key (US)", value="", type="password") # 填入你的Key
    gie_key = st.sidebar.text_input("GIE Key (EU)", value="", type="password") # 填入你的Key

# Settings
with st.sidebar.expander("⚙️ Calc Settings", expanded=False):
    freight_cost = st.sidebar.slider("Freight ($/MMBtu)", 0.2, 3.0, 0.8)
    liquefaction_cost = st.sidebar.number_input("Liq Cost", value=3.0)

# Manual Override
st.sidebar.markdown("---")
manual_ttf = st.sidebar.number_input("Manual TTF (€/MWh)", value=0.0)

# --- Functions ---

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
    url = "https://api.eia.gov/v2/natural-gas/stor/wkly/data/"
    params = {
        'api_key': api_key, 'frequency': 'weekly', 'data[0]': 'value',
        'facets[series][]': 'NW2_EPG0_SWO_R48_BCF', 
        'sort[0][column]': 'period', 'sort[0][direction]': 'desc', 'length': 2
    }
    try:
        r = requests.get(url, params=params).json()
        # 增强解析逻辑
        d = r.get('response', {}).get('data', []) or r.get('data', [])
        if not d: return None, "Empty Data"
        return {"val": float(d[0]['value']), "chg": float(d[0]['value']) - float(d[1]['value']), "date": d[0]['period']}, "OK"
    except Exception as e:
        return None, str(e)

def get_gie_storage(api_key):
    if not api_key: return None, "No Key"
    try:
        r = requests.get("https://agsi.gie.eu/api", headers={"x-key": api_key}, params={'type': 'eu'}).json()
        d = r['data'][0]
        return {"full": float(d['full']), "val": float(d['gasInStorage']), "date": d['gasDayStart']}, "OK"
    except Exception as e:
        return None, str(e)

# --- Main Layout ---

st.title("🚢 Global LNG Trading Desk")

# 1. 库存
st.subheader("1. Inventory Fundamentals")
c1, c2 = st.columns(2)
eia_data, eia_msg = get_eia_storage(eia_key)
gie_data, gie_msg = get_gie_storage(gie_key)

with c1:
    if eia_data:
        st.metric("🇺🇸 US Storage (EIA)", f"{eia_data['val']:.0f} Bcf", f"{eia_data['chg']:.0f} Bcf (WoW)")
        st.caption(f"Period Ending: {eia_data['date']} (Released +6 days)")
    else:
        st.info(f"US Data: {eia_msg}")

with c2:
    if gie_data:
        st.metric("🇪🇺 EU Storage (GIE)", f"{gie_data['full']:.2f}%", f"{gie_data['val']:.1f} TWh")
        st.caption(f"Gas Day: {gie_data['date']}")
    else:
        st.info(f"EU Data: {gie_msg}")

st.divider()

# 2. 价格 & 套利
st.subheader("2. Price & Arbitrage")
prices = get_market_data()
k1, k2, k3, k4 = st.columns(4)

k1.metric("Henry Hub", f"${prices['HH']['price']:.2f}", f"{prices['HH']['change']:.2f}")
k2.metric("TTF (EU)", f"€{prices['TTF']['price']:.2f}", f"{prices['TTF']['change']:.2f}")
k3.metric("JKM (Asia)", f"${prices['JKM']['price']:.2f}", f"{prices['JKM']['change']:.2f}")
k4.metric("Brent Oil", f"${prices['Oil']['price']:.2f}", f"{prices['Oil']['change']:.2f}")

# Arb Calculation
if prices['HH']['price'] > 0 and prices['TTF']['price'] > 0:
    hh = prices['HH']['price']
    ttf_usd = (prices['TTF']['price'] * 1.05) / 3.412 # 简易换算
    cost = (hh * 1.15) + liquefaction_cost + freight_cost
    spread = (ttf_usd - 1.0) - cost
    
    st.markdown("##### 🇺🇸 ➔ 🇪🇺 Arb Calculator")
    ac1, ac2 = st.columns([1,3])
    with ac1:
        if spread > 0:
            st.success(f"PROFIT: ${spread:.2f}")
        else:
            st.error(f"LOSS: ${spread:.2f}")
    with ac2:
        st.progress(min(max((spread + 2)/6, 0.0), 1.0)) # 简单的可视化条
        st.caption(f"Est. Netback based on current HH & TTF. Freight: ${freight_cost}")

st.divider()

# 3. 气象云图 (嵌入 Windy)
st.subheader("3. Live Weather Models (GFS/ECMWF)")
st.caption("Interactive Map: Select 'Temp' layer and toggle between ECMWF/GFS in bottom right.")

# 嵌入 Windy.com
# 这是一个交易员的捷径：直接把最专业的工具嵌入进来，而不是自己造轮子。
# 默认定位在大西洋，方便同时看欧美。
components.iframe(
    src="https://embed.windy.com/embed2.html?lat=43.0&lon=-40.0&detailLat=43.0&detailLon=-40.0&width=1000&height=450&zoom=3&level=surface&overlay=temp&product=ecmwf&menu=&message=&marker=&calendar=now&pressure=&type=map&location=coordinates&detail=&metricWind=default&metricTemp=default&radarRange=-1",
    height=450,
    scrolling=False
)

st.divider()

# 4. AI 消息面 (Updated for Gemini 3.0 Flash)
st.subheader("4. AI Market Sentiment (Powered by Gemini 3.0 Flash)")

# 增加一个输入框，让你可以向 AI 提问 (Chat功能)
user_query = st.text_input("Ask AI Analyst (e.g., 'Summarize LNG supply risks in Australia'):")

if st.button("🚀 Analyze News & Query") or user_query:
    if not gemini_key:
        st.error("⚠️ System Halted: Missing Gemini API Key in Sidebar.")
    else:
        rss_urls = [
            "http://feeds.reuters.com/reuters/energyNews",
            "https://lngprime.com/feed/",
            "https://www.naturalgasintel.com/feed/"
        ]
        
        news_context = []
        with st.spinner("📡 Scanning Global Energy Feeds..."):
            for url in rss_urls:
                try:
                    # 模拟浏览器 User-Agent 防止被反爬拦截
                    d = feedparser.parse(url, agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
                    for e in d.entries[:3]: # 每个源取前3条
                        news_context.append(f"- [{e.source.get('title', 'Web')}] {e.title}")
                except: 
                    pass
        
        if news_context:
            try:
                # --- 核心升级点：切换到 gemini-3.0-flash ---
                genai.configure(api_key=gemini_key)
                
                # 注意：模型名称需要匹配 Google 官方最新的发布名称
                # 如果 3.0 还未在 SDK 列表完全生效，代码会自动回退尝试，这里我们强制指定
                model_name = 'gemini-3.0-flash' 
                
                model = genai.GenerativeModel(model_name)
                
                # 构建更高级的 Prompt
                base_prompt = f"""
                You are a Senior LNG Trader on a Wall Street desk.
                
                Current Market News Headlines:
                {chr(10).join(news_context)}
                
                Task:
                1. Analyze the 'Market Sentiment' (Bullish/Bearish/Neutral) based strictly on these headlines.
                2. Identify any 'Supply Disruptions' or 'Weather Shocks'.
                3. Give a confidence score (0-10) for price volatility.
                """
                
                # 如果用户有额外提问，把提问加进去
                if user_query:
                    final_prompt = base_prompt + f"\n\nUSER QUESTION: {user_query}\nAnswer the user's question using the news context and your knowledge."
                else:
                    final_prompt = base_prompt

                response = model.generate_content(final_prompt)
                
                st.markdown("### 🧠 Analyst Report")
                st.info(response.text)
                
            except Exception as e:
                st.error(f"AI Connection Error: {e}")
                st.caption("Tip: Check if your API Key supports the 3.0 model, or revert to 'gemini-1.5-flash'.")
        else:
            st.warning("No news fetched. Check your internet connection.")
