import streamlit as st
import yfinance as yf
import requests
import feedparser
import google.generativeai as genai
import streamlit.components.v1 as components
from datetime import datetime

# --- 页面配置 ---
st.set_page_config(page_title="LNG Trading Desk V5.2", layout="wide", page_icon="🚢")

# --- 样式优化 ---
st.markdown("""
    <style>
    .stMetric {background-color: #f8f9fa; padding: 10px; border-radius: 8px; border: 1px solid #e9ecef;}
    .stAlert {padding: 0.5rem;}
    </style>
    """, unsafe_allow_html=True)

# --- 侧边栏 ---
st.sidebar.title("⚡ LNG Pro V5.2")
st.sidebar.caption("Live Intelligence & Arbitrage")

with st.sidebar.expander("🔑 API Keys", expanded=True):
    gemini_key = st.sidebar.text_input("Gemini Key", type="password")
    eia_key = st.sidebar.text_input("EIA Key (US)", type="password")
    gie_key = st.sidebar.text_input("GIE Key (EU)", type="password")

with st.sidebar.expander("⚙️ Calc Settings", expanded=False):
    freight_cost = st.sidebar.slider("Freight ($/MMBtu)", 0.2, 3.0, 0.8)
    liquefaction_cost = st.sidebar.number_input("Liq Cost", value=3.0)

manual_ttf = st.sidebar.number_input("Manual TTF (€/MWh)", value=0.0)

# --- 核心数据函数 ---

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

# --- 新闻抓取增强版 ---
def fetch_news_headlines():
    # 伪装成浏览器
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    
    # 扩充的新闻源矩阵 (RSS Matrix)
    sources = [
        ("LNG Prime", "https://lngprime.com/feed/"),
        ("OilPrice", "https://oilprice.com/rss/main"),
        ("CNBC Energy", "https://www.cnbc.com/id/19836768/device/rss/rss.html"),
        ("Rigzone", "https://www.rigzone.com/news/rss/rigzone_latest.aspx"),
        ("Gas World", "https://www.gasworld.com/feed/"),
        ("EIA Reports", "https://www.eia.gov/rss/naturalgas.xml"),
        ("Investing.com", "https://www.investing.com/rss/commodities.rss"),
        ("Offshore Energy", "https://www.offshore-energy.biz/feed/"),
        ("Natural Gas Intel", "https://www.naturalgasintel.com/feed/"),
    ]
    
    headlines = []
    log = []
    
    for name, url in sources:
        try:
            # 先用 requests 获取内容 (比直接用 feedparser 更稳)
            response = requests.get(url, headers=headers, timeout=4)
            if response.status_code == 200:
                feed = feedparser.parse(response.content)
                count = 0
                for entry in feed.entries[:3]: # 每个源取前3条
                    headlines.append(f"- [{name}] {entry.title}")
                    count += 1
                log.append(f"✅ {name}: Fetched {count} items")
            else:
                log.append(f"⚠️ {name}: HTTP {response.status_code}")
        except Exception as e:
            log.append(f"❌ {name}: Failed ({str(e)})")
            
    return headlines, log

# --- 主界面 ---

st.title("🚢 Global LNG Trading Desk V5.2")

# 1. Fundamentals
st.subheader("1. Inventory & Fundamentals")
c1, c2 = st.columns(2)
eia_data, eia_msg = get_eia_storage(eia_key)
gie_data, gie_msg = get_gie_storage(gie_key)

with c1:
    if eia_data:
        st.metric("🇺🇸 US Storage (EIA)", f"{eia_data['val']:.0f} Bcf", f"{eia_data['chg']:.0f} Bcf")
    else:
        st.metric("🇺🇸 US Storage (EIA)", "N/A", eia_msg)

with c2:
    if gie_data:
        st.metric("🇪🇺 EU Storage (GIE)", f"{gie_data['full']:.2f}%", f"{gie_data['val']:.1f} TWh")
    else:
        st.metric("🇪🇺 EU Storage (GIE)", "N/A", gie_msg)

# 2. Price & Arb
st.divider()
st.subheader("2. Market Prices & Arbitrage")
prices = get_market_data()
k1, k2, k3, k4 = st.columns(4)

k1.metric("Henry Hub", f"${prices['HH']['price']:.2f}", f"{prices['HH']['change']:.2f}")
k2.metric("TTF (EU)", f"€{prices['TTF']['price']:.2f}", f"{prices['TTF']['change']:.2f}")
k3.metric("JKM (Asia)", f"${prices['JKM']['price']:.2f}", f"{prices['JKM']['change']:.2f}")
k4.metric("Brent Oil", f"${prices['Oil']['price']:.2f}", f"{prices['Oil']['change']:.2f}")

# Arb Logic
if prices['HH']['price'] > 0 and prices['TTF']['price'] > 0:
    hh = prices['HH']['price']
    ttf_usd = (prices['TTF']['price'] * 1.05) / 3.412
    cost = (hh * 1.15) + liquefaction_cost + freight_cost
    spread = (ttf_usd - 1.0) - cost
    
    if spread > 0:
        st.success(f"✅ ARB OPEN: Profit ${spread:.2f}/MMBtu (Buy US -> Sell EU)")
    else:
        st.error(f"❌ ARB CLOSED: Loss ${spread:.2f}/MMBtu")
else:
    st.warning("Waiting for Price Data...")

# 3. Weather
st.divider()
st.subheader("3. Live Weather Models (Windy)")
components.iframe(
    src="https://embed.windy.com/embed2.html?lat=40.0&lon=-50.0&detailLat=43.0&detailLon=-40.0&width=1000&height=450&zoom=3&level=surface&overlay=temp&product=ecmwf&menu=&message=&marker=&calendar=now&pressure=&type=map&location=coordinates&detail=&metricWind=default&metricTemp=default&radarRange=-1",
    height=450,
    scrolling=False
)

# 4. AI Analysis
st.divider()
st.subheader("4. AI Market Intelligence (Multi-Source)")

user_query = st.text_input("💬 Ask Gemini Analyst (e.g. 'Summarize supply risks'):")

if st.button("🚀 Fetch News & Analyze") or user_query:
    if not gemini_key:
        st.error("Please enter Gemini API Key in Sidebar")
    else:
        with st.spinner("🕷️ Crawling global energy feeds..."):
            headlines, fetch_log = fetch_news_headlines()
        
        # 调试信息：告诉你哪些源成功了，哪些失败了
        with st.expander("📡 Source Status Log (Debug)", expanded=False):
            for log_item in fetch_log:
                st.write(log_item)
        
        if headlines:
            try:
                genai.configure(api_key=gemini_key)
                # 尝试使用 3.0，如果失败回退到 1.5
                model_name = "gemini-1.5-flash" 
                
                # 如果你想尝试3.0，可以把上面改成 "gemini-3.0-flash"
                # 但目前为了稳定性推荐 1.5-flash
                
                model = genai.GenerativeModel(model_name)
                
                prompt = f"""
                You are a Senior LNG Trader. 
                Analyze these latest news headlines and summarize the key market sentiment.
                
                Headlines:
                {chr(10).join(headlines)}
                
                USER QUESTION: {user_query if user_query else "Provide a general market summary."}
                
                Output Format:
                1. **Sentiment**: Bullish/Bearish/Neutral
                2. **Key Drivers**: 3 bullet points
                3. **Critical Alerts**: Any supply outages?
                """
                
                with st.spinner("🧠 Gemini is thinking..."):
                    response = model.generate_content(prompt)
                    st.markdown(response.text)
            except Exception as e:
                st.error(f"AI Error: {str(e)}")
        else:
            st.warning("No headlines fetched. Please check the Debug Log above to see why.")
