import streamlit as st
import yfinance as yf
import requests
import feedparser
import google.generativeai as genai
import streamlit.components.v1 as components
from datetime import datetime, timedelta, timezone
from time import mktime

# --- 页面配置 ---
st.set_page_config(page_title="LNG Trading Desk V5.5", layout="wide", page_icon="🚢")

# --- CSS 样式优化 ---
st.markdown("""
    <style>
    .stMetric {background-color: #f8f9fa; padding: 10px; border-radius: 8px; border: 1px solid #e9ecef;}
    
    /* News Ticker 样式 */
    .ticker-wrap {
        width: 100%;
        overflow: hidden;
        background-color: #333;
        color: #0f0; /* 经典的终端绿 */
        padding: 10px;
        white-space: nowrap;
        box-sizing: border-box;
        border-radius: 5px;
        margin-bottom: 20px;
        font-family: 'Courier New', Courier, monospace;
    }
    .ticker {
        display: inline-block;
        padding-left: 100%;
        animation: ticker 60s linear infinite;
    }
    @keyframes ticker {
        0%   { transform: translate3d(0, 0, 0); }
        100% { transform: translate3d(-100%, 0, 0); }
    }
    .ticker-item {
        display: inline-block;
        padding: 0 2rem;
    }
    
    /* 表格链接样式 */
    a { text-decoration: none; font-weight: bold; color: #0068c9; }
    a:hover { text-decoration: underline; color: #ff4b4b; }
    
    /* 总结模块样式 */
    .summary-box {
        background-color: #e8f4f8;
        padding: 15px;
        border-radius: 10px;
        border-left: 5px solid #0068c9;
        margin-top: 20px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 侧边栏 ---
st.sidebar.title("⚡ LNG Pro V5.5")
st.sidebar.caption("Live Feed + Sentiment Summary")

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
        ("EIA Reports", "https://www.eia.gov/rss/naturalgas.xml"),
        ("Investing.com", "https://www.investing.com/rss/commodities.rss"),
        ("Offshore Energy", "https://www.offshore-energy.biz/feed/"),
        ("Natural Gas Intel", "https://www.naturalgasintel.com/feed/"),
    ]
    
    news_items = []
    log = []
    
    for name, url in sources:
        try:
            resp = requests.get(url, headers=headers, timeout=4)
            if resp.status_code == 200:
                feed = feedparser.parse(resp.content)
                for entry in feed.entries[:3]:
                    try:
                        if hasattr(entry, 'published_parsed'):
                            dt_utc = datetime.fromtimestamp(mktime(entry.published_parsed), timezone.utc)
                        else:
                            dt_utc = datetime.now(timezone.utc)
                        dt_bj = dt_utc.astimezone(timezone(timedelta(hours=8)))
                        time_str = dt_bj.strftime("%m-%d %H:%M")
                    except:
                        time_str = "Unknown"
                        dt_bj = datetime.now()
                    
                    news_items.append({
                        "source": name,
                        "title": entry.title,
                        "link": entry.link,
                        "time_str": time_str,
                        "dt_obj": dt_bj
                    })
                log.append(f"✅ {name}")
            else:
                log.append(f"⚠️ {name} ({resp.status_code})")
        except:
            log.append(f"❌ {name}")
    
    news_items.sort(key=lambda x: x['dt_obj'].timestamp(), reverse=True)
    return news_items, log

def get_working_model(api_key):
    genai.configure(api_key=api_key)
    try:
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        for m in models:
            if 'flash' in m.lower(): return m
        for m in models:
            if 'gemini' in m.lower(): return m
        return "models/gemini-pro"
    except:
        return "models/gemini-pro"

# --- 主界面 ---

st.title("🚢 Global LNG Trading Desk V5.5")

# 1. 跑马灯
ticker_placeholder = st.empty()

# 2. Fundamentals
c1, c2 = st.columns(2)
eia_data, eia_msg = get_eia_storage(eia_key)
gie_data, gie_msg = get_gie_storage(gie_key)
with c1:
    if eia_data: st.metric("🇺🇸 US Storage (EIA)", f"{eia_data['val']:.0f} Bcf", f"{eia_data['chg']:.0f} Bcf")
    else: st.metric("🇺🇸 US Storage", "N/A", eia_msg)
with c2:
    if gie_data: st.metric("🇪🇺 EU Storage (GIE)", f"{gie_data['full']:.2f}%", f"{gie_data['val']:.1f} TWh")
    else: st.metric("🇪🇺 EU Storage", "N/A", gie_msg)

st.divider()

# 3. Price & Arb
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

st.divider()

# 4. AI Analysis & Live Feed
st.subheader("4. Live Intelligence (Beijing Time)")

user_query = st.text_input("💬 Filter (e.g. 'Strikes'):")

if st.button("🔄 Refresh News & Analyze") or user_query:
    if not gemini_key:
        st.error("Need Gemini Key")
    else:
        with st.spinner("🕷️ Updating Live Feed & Generating Summary..."):
            news_items, fetch_log = fetch_news_headlines()
            model_name = get_working_model(gemini_key)
            
            # 更新跑马灯
            if news_items:
                ticker_html = '<div class="ticker-wrap"><div class="ticker">'
                for item in news_items[:10]:
                    ticker_html += f'<div class="ticker-item">{item["time_str"]} {item["title"]}</div>'
                ticker_html += '</div></div>'
                ticker_placeholder.markdown(ticker_html, unsafe_allow_html=True)

        with st.expander("📡 Source Log"):
            st.write(fetch_log)
        
        if news_items:
            try:
                genai.configure(api_key=gemini_key)
                model = genai.GenerativeModel(model_name)
                
                # --- V5.5 升级 Prompt: 强制要求写总结 ---
                news_text_block = ""
                for item in news_items[:15]:
                    news_text_block += f"Time: {item['time_str']} | Source: {item['source']} | Title: {item['title']} | URL: {item['link']}\n"

                prompt = f"""
                You are a Head of LNG Trading.
                
                Input Data (Newest First):
                {news_text_block}
                
                User Filter: {user_query if user_query else "None"}

                Task 1: Detailed Table
                Create a markdown table. 
                **CRITICAL**: The 'Headline' column MUST be a markdown link: `[Title](URL)`.
                Columns: Time (BJ), Source, Headline, Sentiment (📈/📉/➖), Impact(1-10), Key Takeaway.

                Task 2: Global Market Sentiment Summary (CRITICAL)
                Below the table, write a section titled "### 🌍 Global Market Sentiment Summary".
                Write a concise, professional paragraph (3-4 sentences) summarizing the overall market direction based on these headlines. 
                Is it Bullish or Bearish overall? What is the biggest driver (Weather? Geopolitics? Supply?)?
                """
                
                with st.spinner("🧠 Analyst is writing summary..."):
                    response = model.generate_content(prompt)
                    st.markdown(response.text)
                    
            except Exception as e:
                st.error(f"AI Error: {str(e)}")
        else:
            st.warning("No news fetched.")
else:
    st.info("Click 'Refresh News' to load the latest timeline.")

# 5. Weather
st.divider()
st.subheader("5. Live Weather (Windy)")
components.iframe(src="https://embed.windy.com/embed2.html?lat=40.0&lon=-50.0&zoom=3&level=surface&overlay=temp&product=ecmwf&menu=&message=&marker=&calendar=now&pressure=&type=map&location=coordinates&detail=&metricWind=default&metricTemp=default&radarRange=-1", height=450)
