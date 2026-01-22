import streamlit as st
import yfinance as yf
import requests
import feedparser
import google.generativeai as genai
import streamlit.components.v1 as components
from datetime import datetime, timedelta, timezone
from time import mktime

# --- 页面配置 ---
st.set_page_config(page_title="LNG Trading Desk V5.4", layout="wide", page_icon="🚢")

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
    a { text-decoration: none; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- 侧边栏 ---
st.sidebar.title("⚡ LNG Pro V5.4")
st.sidebar.caption("Live Feed & Beijing Time Sort")

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

# --- 核心升级：新闻抓取 + 北京时间转换 ---
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
    
    news_items = [] # 存储结构化数据
    log = []
    
    for name, url in sources:
        try:
            resp = requests.get(url, headers=headers, timeout=4)
            if resp.status_code == 200:
                feed = feedparser.parse(resp.content)
                for entry in feed.entries[:3]: # 每个源取前3条
                    # --- 时间处理逻辑 ---
                    try:
                        if hasattr(entry, 'published_parsed'):
                            # 将 struct_time 转为 UTC datetime
                            dt_utc = datetime.fromtimestamp(mktime(entry.published_parsed), timezone.utc)
                        else:
                            dt_utc = datetime.now(timezone.utc) # 没有时间就用现在
                        
                        # 转北京时间 (UTC+8)
                        dt_bj = dt_utc.astimezone(timezone(timedelta(hours=8)))
                        time_str = dt_bj.strftime("%m-%d %H:%M")
                    except:
                        time_str = "Unknown Time"
                        dt_bj = datetime.now() # 排序防报错
                    
                    # 存储数据
                    news_items.append({
                        "source": name,
                        "title": entry.title,
                        "link": entry.link,
                        "time_str": time_str,
                        "dt_obj": dt_bj # 用于排序
                    })
                log.append(f"✅ {name}")
            else:
                log.append(f"⚠️ {name} ({resp.status_code})")
        except:
            log.append(f"❌ {name}")
    
    # --- 排序：按北京时间从新到旧 ---
    # x['dt_obj'] 可能会有 offset-naive 和 offset-aware 的问题，这里做个简单处理
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

st.title("🚢 Global LNG Trading Desk V5.4")

# 1. 跑马灯 (Breaking News Ticker)
# 这里先用占位符，等抓取到新闻后再填充
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

# 自动刷新机制 (手动点击刷新，因为Streamlit自动刷新需要第三方插件)
if st.button("🔄 Refresh News & Analyze") or user_query:
    if not gemini_key:
        st.error("Need Gemini Key")
    else:
        with st.spinner("🕷️ Updating Live Feed (Sorted by Beijing Time)..."):
            news_items, fetch_log = fetch_news_headlines()
            model_name = get_working_model(gemini_key)
            
            # --- 更新跑马灯 ---
            if news_items:
                ticker_html = '<div class="ticker-wrap"><div class="ticker">'
                for item in news_items[:10]: # 只滚播最新的10条
                    ticker_html += f'<div class="ticker-item">{item["time_str"]} {item["title"]}</div>'
                ticker_html += '</div></div>'
                ticker_placeholder.markdown(ticker_html, unsafe_allow_html=True)

        with st.expander("📡 Source Log"):
            st.write(fetch_log)
        
        if news_items:
            try:
                genai.configure(api_key=gemini_key)
                model = genai.GenerativeModel(model_name)
                
                # --- 构建 Prompt (包含链接信息) ---
                # 我们构建一个特殊的格式传给AI： Title|Link|Source
                news_text_block = ""
                for item in news_items[:15]: # 只分析最新的15条，避免Token溢出
                    news_text_block += f"Time: {item['time_str']} | Source: {item['source']} | Title: {item['title']} | URL: {item['link']}\n"

                prompt = f"""
                You are a Senior LNG Trader. 
                
                Input Data (Newest First):
                {news_text_block}
                
                Task:
                Create a markdown table. 
                **CRITICAL**: The 'Headline' column MUST be a markdown link using the URL provided. Format: `[Title](URL)`.
                
                Columns:
                1. **Time (BJ)**: Copy the time exactly.
                2. **Source**: Source name.
                3. **Headline**: The Clickable Markdown Link.
                4. **Sentiment**: 📈/📉/➖.
                5. **Impact (1-10)**.
                6. **Key Takeaway**: Very short summary.

                User Filter: {user_query if user_query else "None"}
                """
                
                with st.spinner("🧠 Analyst is processing links..."):
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
