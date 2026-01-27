import streamlit as st
import yfinance as yf
import requests
import feedparser
import google.generativeai as genai
import streamlit.components.v1 as components
from datetime import datetime, timedelta, timezone
from time import mktime

# --- 页面配置 ---
st.set_page_config(page_title="LNG Trading Desk V6.1", layout="wide", page_icon="🚢")

# --- CSS 样式 (融合版) ---
st.markdown("""
    <style>
    .stMetric {background-color: #f8f9fa; padding: 10px; border-radius: 8px; border: 1px solid #e9ecef;}
    
    /* 跑马灯样式 */
    .ticker-wrap {
        width: 100%; overflow: hidden; background-color: #333; color: #0f0;
        padding: 10px; white-space: nowrap; box-sizing: border-box;
        border-radius: 5px; margin-bottom: 20px; font-family: 'Courier New', monospace;
    }
    .ticker { display: inline-block; padding-left: 100%; animation: ticker 60s linear infinite; }
    @keyframes ticker { 0% { transform: translate3d(0, 0, 0); } 100% { transform: translate3d(-100%, 0, 0); } }
    .ticker-item { display: inline-block; padding: 0 2rem; }
    
    /* 链接样式 */
    a { text-decoration: none; font-weight: bold; color: #0068c9; }
    a:hover { text-decoration: underline; color: #ff4b4b; }
    
    /* 总结模块样式 */
    .summary-box {
        background-color: #e8f4f8; padding: 15px; border-radius: 10px;
        border-left: 5px solid #0068c9; margin-top: 20px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 侧边栏 ---
st.sidebar.title("⚡ LNG Pro V6.1")
st.sidebar.caption("Full Hybrid: News Feed + Port Radar")

with st.sidebar.expander("🔑 API Keys", expanded=True):
    gemini_key = st.sidebar.text_input("Gemini Key", type="password")
    eia_key = st.sidebar.text_input("EIA Key (US)", type="password")
    gie_key = st.sidebar.text_input("GIE Key (EU)", type="password")

with st.sidebar.expander("⚙️ Calc Settings", expanded=False):
    freight_cost = st.sidebar.slider("Freight ($/MMBtu)", 0.2, 3.0, 0.8)
    liquefaction_cost = st.sidebar.number_input("Liq Cost", value=3.0)

manual_ttf = st.sidebar.number_input("Manual TTF (€/MWh)", value=0.0)

# --- 数据函数 (V6.0 库存逻辑 + V5.5 市场数据) ---

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

# EIA 同比逻辑 (保留 V6.0 的精华)
def get_eia_storage_analysis(api_key):
    if not api_key: return None, "No Key"
    try:
        url = "https://api.eia.gov/v2/natural-gas/stor/wkly/data/"
        params = {
            'api_key': api_key, 'frequency': 'weekly', 'data[0]': 'value',
            'facets[series][]': 'NW2_EPG0_SWO_R48_BCF', 
            'sort[0][column]': 'period', 'sort[0][direction]': 'desc', 'length': 60
        }
        r = requests.get(url, params=params, timeout=5).json()
        d = r.get('response', {}).get('data', []) or r.get('data', [])
        if len(d) < 53: return None, "Not enough history"
        
        curr_val = float(d[0]['value'])
        last_year_val = float(d[52]['value'])
        yoy_diff = curr_val - last_year_val
        yoy_pct = (yoy_diff / last_year_val) * 100
        change = float(d[0]['value']) - float(d[1]['value'])
        
        return {"val": curr_val, "chg": change, "date": d[0]['period'], "yoy_diff": yoy_diff, "yoy_pct": yoy_pct, "last_year_val": last_year_val}, "OK"
    except Exception as e:
        return None, str(e)

# GIE 同比逻辑 (保留 V6.0 的精华)
def get_gie_storage_analysis(api_key):
    if not api_key: return None, "No Key"
    try:
        url = "https://agsi.gie.eu/api"
        headers = {"x-key": api_key}
        r_curr = requests.get(url, headers=headers, params={'type': 'eu'}, timeout=5).json()
        d_curr = r_curr['data'][0]
        
        curr_date = datetime.strptime(d_curr['gasDayStart'], "%Y-%m-%d")
        last_year_date = curr_date - timedelta(days=365)
        r_hist = requests.get(url, headers=headers, params={'type': 'eu', 'date': last_year_date.strftime("%Y-%m-%d")}, timeout=5).json()
        d_hist = r_hist['data'][0]
        
        curr_full = float(d_curr['full'])
        last_full = float(d_hist['full'])
        return {"full": curr_full, "val": float(d_curr['gasInStorage']), "date": d_curr['gasDayStart'], "yoy_diff": curr_full - last_full, "last_year_full": last_full}, "OK"
    except Exception as e:
        return None, str(e)

# 新闻抓取 (保留 V5.5 的北京时间和链接)
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
                    news_items.append({"source": name, "title": entry.title, "link": entry.link, "time_str": time_str, "dt_obj": dt_bj})
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

st.title("🚢 Global LNG Trading Desk V6.1")

# 1. 跑马灯 (V5.5 Feature)
ticker_placeholder = st.empty()

# 2. 基本面库存 (V6.0 YoY Logic)
st.subheader("1. Inventory Context (vs Last Year)")
c1, c2 = st.columns(2)
eia_data, eia_msg = get_eia_storage_analysis(eia_key)
gie_data, gie_msg = get_gie_storage_analysis(gie_key)

with c1:
    if eia_data:
        st.metric("🇺🇸 US Storage", f"{eia_data['val']:.0f} Bcf", f"{eia_data['chg']:.0f} Bcf")
        color = "green" if eia_data['yoy_diff'] > 0 else "red"
        st.markdown(f"<small>YoY: <span style='color:{color}'>{eia_data['yoy_diff']:.0f} Bcf ({eia_data['yoy_pct']:.1f}%)</span> vs Last Year</small>", unsafe_allow_html=True)
    else:
        st.metric("🇺🇸 US Storage", "N/A", eia_msg)

with c2:
    if gie_data:
        st.metric("🇪🇺 EU Storage", f"{gie_data['full']:.2f}%", f"{gie_data['val']:.1f} TWh")
        color = "green" if gie_data['yoy_diff'] > 0 else "red"
        st.markdown(f"<small>YoY: <span style='color:{color}'>{gie_data['yoy_diff']:.2f}%</span> vs Last Year</small>", unsafe_allow_html=True)
    else:
        st.metric("🇪🇺 EU Storage", "N/A", gie_msg)

st.divider()

# 3. 价格 & 套利 (V5.5 Logic)
st.subheader("2. Prices & Arb Monitor")
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

# 4. 港口雷达 (Port Radar) - JS 注入修复版
st.subheader("3. Strategic Port Radar (Live Ships)")
st.caption("Tracking LNG Tankers at Key Chokepoints (Official Widget)")

port_option = st.selectbox("Select Radar View:", ["🇺🇸 Sabine Pass (US Export)", "🇳🇱 Rotterdam (EU Import)", "🇯🇵 Tokyo Bay (Asia Import)"])

# 设置坐标参数
if "Sabine" in port_option:
    lat, lon, zoom = 29.70, -93.85, 10
elif "Rotterdam" in port_option:
    lat, lon, zoom = 51.95, 4.05, 9
else: # Tokyo
    lat, lon, zoom = 35.50, 139.80, 9

# --- 核心修复：使用 JavaScript 嵌入 (比 iframe 更稳) ---
# 这是 VesselFinder 官方提供的标准嵌入代码，兼容性更好
vesselfinder_html = f"""
    <div style="width:100%; height:450px; border:1px solid #ccc; border-radius:10px; overflow:hidden;">
        <script type="text/javascript">
            width='100%';          // 宽度
            height='450';          // 高度
            border='0';            // 边框
            shownames='true';      // 显示船名
            latitude='{lat}';      // 动态纬度
            longitude='{lon}';     // 动态经度
            zoom='{zoom}';         // 缩放级别
            maptype='1';           // 地图类型 (1=普通地图)
            trackvessel='0';       // 不追踪特定船只
            fleet='';              // 不显示特定船队
        </script>
        <script type="text/javascript" src="https://www.vesselfinder.com/aismap.js"></script>
    </div>
"""

# 使用 components.html 渲染这段 JS
components.html(vesselfinder_html, height=450)

# 备用方案：如果还是加载不出来，提供一个漂亮的跳转按钮
link_url = f"https://www.vesselfinder.com/?lat={lat}&lon={lon}&zoom={zoom}"
st.markdown(f"""
    <div style="text-align: center; margin-top: 10px;">
        <a href="{link_url}" target="_blank" style="
            display: inline-block;
            padding: 10px 20px;
            background-color: #0068c9;
            color: white;
            text-decoration: none;
            border-radius: 5px;
            font-weight: bold;">
            🚀 Map blocked? Click to open VesselFinder directly
        </a>
    </div>
""", unsafe_allow_html=True)

st.divider()

# 5. AI 智能情报 (V5.5 完整版：链接+总结)
st.subheader("4. Live Intelligence (Beijing Time)")

user_query = st.text_input("💬 Filter News (e.g. 'Strikes'):")

if st.button("🔄 Refresh News & Analyze") or user_query:
    if not gemini_key:
        st.error("Need Gemini Key")
    else:
        with st.spinner("🕷️ Updating Feed & Generating Summary..."):
            news_items, fetch_log = fetch_news_headlines()
            model_name = get_working_model(gemini_key)
            
            # 跑马灯填充
            if news_items:
                ticker_html = '<div class="ticker-wrap"><div class="ticker">'
                for item in news_items[:10]:
                    ticker_html += f'<div class="ticker-item">{item["time_str"]} {item["title"]}</div>'
                ticker_html += '</div></div>'
                ticker_placeholder.markdown(ticker_html, unsafe_allow_html=True)
            
            # AI 分析
            if news_items:
                genai.configure(api_key=gemini_key)
                model = genai.GenerativeModel(model_name)
                
                news_text = ""
                for item in news_items[:15]:
                    news_text += f"Time: {item['time_str']} | Source: {item['source']} | Title: {item['title']} | URL: {item['link']}\n"
                
                # V5.5 Prompt
                prompt = f"""
                You are a Head of LNG Trading. Input Data (Newest First):
                {news_text}
                User Filter: {user_query if user_query else "None"}

                Task 1: Detailed Table
                Create a markdown table. 
                **CRITICAL**: 'Headline' column MUST be a link: `[Title](URL)`.
                Columns: Time (BJ), Source, Headline, Sentiment (📈/📉/➖), Impact(1-10), Key Takeaway.

                Task 2: Global Market Sentiment Summary (CRITICAL)
                Below table, write a section "### 🌍 Global Market Sentiment Summary".
                Write a concise paragraph summarizing market direction (Bullish/Bearish) and biggest driver.
                """
                
                response = model.generate_content(prompt)
                st.markdown(response.text)
                
                with st.expander("📡 Source Log"):
                    st.write(fetch_log)
            else:
                st.warning("No news fetched.")

# 6. 天气 (Windy)
st.divider()
st.subheader("5. Live Weather (Windy)")
components.iframe(src="https://embed.windy.com/embed2.html?lat=40.0&lon=-50.0&zoom=3&level=surface&overlay=temp&product=ecmwf&menu=&message=&marker=&calendar=now&pressure=&type=map&location=coordinates&detail=&metricWind=default&metricTemp=default&radarRange=-1", height=450)
