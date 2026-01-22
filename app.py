import streamlit as st
import yfinance as yf
import feedparser
import google.generativeai as genai
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
from time import mktime

# ==========================================
# 0. 全局配置与常量
# ==========================================
st.set_page_config(
    page_title="LNG Trading Dashboard V3",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 估算参数
TTF_CONVERSION_FACTOR = 0.31  # 粗略换算: (1 EUR ≈ 1.05 USD) / (1 MWh ≈ 3.412 MMBtu) ≈ 0.307
ARB_COST_ESTIMATE = 8.0       # USD/MMBtu (包含液化费、海运费、再气化费)

# 自定义 CSS (V3版 - 更紧凑、更专业)
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
    .metric-label { font-size: 0.9em; color: #666; font-weight: 500; }
    .metric-value { font-size: 1.6em; font-weight: 700; color: #333; margin: 5px 0; }
    .metric-delta { font-size: 0.9em; font-weight: 600; }
    
    .arb-box-open {
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        color: #155724;
        padding: 15px;
        border-radius: 8px;
        text-align: center;
        margin-bottom: 20px;
    }
    .arb-box-closed {
        background-color: #f8d7da;
        border: 1px solid #f5c6cb;
        color: #721c24;
        padding: 15px;
        border-radius: 8px;
        text-align: center;
        margin-bottom: 20px;
    }
    .news-item {
        border-bottom: 1px solid #eee;
        padding: 10px 0;
    }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 1. Sidebar: 设置
# ==========================================
st.sidebar.header("⚙️ Configuration")
api_key = st.sidebar.text_input("Google Gemini API Key", type="password")
ai_enabled = False
if api_key:
    try:
        genai.configure(api_key=api_key)
        ai_enabled = True
        st.sidebar.success("AI Analytics: ON")
    except:
        st.sidebar.error("API Key Invalid")

st.sidebar.markdown("---")
st.sidebar.markdown(f"""
**Arb Calculation Logic:**
- **Cost Est:** ${ARB_COST_ESTIMATE} / MMBtu
- **Conv Factor:** {TTF_CONVERSION_FACTOR}
- *Formula: (TTF * {TTF_CONVERSION_FACTOR}) - HH*
""")

# ==========================================
# 2. 数据处理核心
# ==========================================
@st.cache_data(ttl=300)
def get_market_data():
    """获取 HH, TTF, JKM, Brent"""
    tickers = ['NG=F', 'TTF=F', 'JKM=F', 'BZ=F']
    try:
        data = yf.download(tickers, period="1mo", group_by='ticker', progress=False)
        res = {}
        
        def get_series(symbol):
            if symbol in data and not data[symbol]['Close'].dropna().empty:
                return data[symbol]['Close'].dropna()
            return None

        res['HH'] = get_series('NG=F')
        res['TTF'] = get_series('TTF=F')
        res['JKM'] = get_series('JKM=F')
        res['BRENT'] = get_series('BZ=F')
        
        return res
    except Exception as e:
        return {}

def calculate_arbitrage(hh_series, ttf_series):
    """计算套利价差序列"""
    if hh_series is None or ttf_series is None:
        return None, 0, 0
    
    # 对齐日期索引
    df = pd.DataFrame({'HH': hh_series, 'TTF': ttf_series}).dropna()
    
    if df.empty:
        return None, 0, 0

    # 换算 TTF (EUR/MWh -> USD/MMBtu)
    df['TTF_USD'] = df['TTF'] * TTF_CONVERSION_FACTOR
    
    # 计算价差 (Spread)
    df['Spread'] = df['TTF_USD'] - df['HH']
    
    latest_spread = df['Spread'].iloc[-1]
    
    # 计算当前是否盈利
    is_open = latest_spread > ARB_COST_ESTIMATE
    
    return df, latest_spread, is_open

def get_news_aggregated():
    """RSS 聚合 (V3 简化版)"""
    sources = [
        ("Reuters", "http://feeds.reuters.com/reuters/energyNews"),
        ("OilPrice", "https://oilprice.com/rss/main"),
        ("LNG Prime", "https://lngprime.com/feed/")
    ]
    items = []
    for name, url in sources:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                dt = datetime.now() # 简化时间处理
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    dt = datetime.fromtimestamp(mktime(entry.published_parsed))
                items.append({
                    "source": name, "title": entry.title, 
                    "link": entry.link, "dt": dt
                })
        except: continue
    return sorted(items, key=lambda x: x['dt'], reverse=True)[:6]

def ai_analyze_market(spread, trend):
    """简单的 AI 市场点评生成"""
    if not ai_enabled: return None
    prompt = f"""
    Current US-EU LNG Spread: ${spread:.2f}/MMBtu.
    Arbitrage Cost Threshold: ${ARB_COST_ESTIMATE}/MMBtu.
    Price Trend: {trend}.
    As a trader, write a 1-sentence strategic action (e.g., "Fix cargoes now", "Wait for volatility").
    """
    try:
        model = genai.GenerativeModel('gemini-pro')
        return model.generate_content(prompt).text
    except: return None

# ==========================================
# 3. UI - Main Layout
# ==========================================
st.title("⚡ LNG Trading Dashboard V3.0")

data = get_market_data()

# --- ROW 1: Key Prices (Macro View) ---
st.markdown("### 1. Market Overview (Price Action)")
c1, c2, c3, c4 = st.columns(4)

def render_metric(col, title, series, prefix, color_invert=False):
    with col:
        if series is None:
            st.markdown(f"""<div class="metric-container"><div class="metric-label">{title}</div><div style="color:#d9534f; margin-top:10px;">No Data</div></div>""", unsafe_allow_html=True)
        else:
            cur = series.iloc[-1]
            prev = series.iloc[-2] if len(series) > 1 else cur
            chg = cur - prev
            # 颜色逻辑: 涨红跌绿(CN) 还是 涨绿跌红(US)? 这里用国际惯例(涨绿)
            color = "#00c853" if chg >= 0 else "#ff5252"
            arrow = "▲" if chg >= 0 else "▼"
            
            st.markdown(f"""
            <div class="metric-container">
                <div class="metric-label">{title}</div>
                <div class="metric-value">{prefix}{cur:.2f}</div>
                <div class="metric-delta" style="color:{color}">{arrow} {chg:.2f}</div>
            </div>
            """, unsafe_allow_html=True)

render_metric(c1, "Henry Hub (US)", data.get('HH'), "$")
render_metric(c2, "Dutch TTF (EU)", data.get('TTF'), "€")
render_metric(c3, "JKM (Asia)", data.get('JKM'), "$")
render_metric(c4, "Brent Oil (Macro)", data.get('BRENT'), "$")

st.markdown("---")

# --- ROW 2: Arbitrage Monitor (The Signal) ---
st.markdown("### 2. US-EU Arbitrage Monitor")

arb_df, current_spread, arb_open = calculate_arbitrage(data.get('HH'), data.get('TTF'))

# 2.1 信号框 (Signal Box)
if arb_df is not None:
    if arb_open:
        st.markdown(f"""
        <div class="arb-box-open">
            <h3>✅ ARBITRAGE WINDOW OPEN</h3>
            <p>Net Spread: <b>${current_spread:.2f}</b> > Cost: ${ARB_COST_ESTIMATE}</p>
            <p style="font-size:0.9em">Exporting US LNG to Europe is theoretically PROFITABLE.</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="arb-box-closed">
            <h3>❌ ARBITRAGE WINDOW CLOSED</h3>
            <p>Net Spread: <b>${current_spread:.2f}</b> < Cost: ${ARB_COST_ESTIMATE}</p>
            <p style="font-size:0.9em">Margins are negative. Wait for spread to widen.</p>
        </div>
        """, unsafe_allow_html=True)

    # 2.2 区域图表 (Spread Area Chart)
    fig = go.Figure()
    
    # 价差区域
    fig.add_trace(go.Scatter(
        x=arb_df.index, y=arb_df['Spread'],
        fill='tozeroy',
        mode='lines',
        name='Spread (TTF-HH)',
        line=dict(color='#1f77b4', width=2),
        fillcolor='rgba(31, 119, 180, 0.2)'
    ))
    
    # 成本线
    fig.add_trace(go.Scatter(
        x=[arb_df.index[0], arb_df.index[-1]],
        y=[ARB_COST_ESTIMATE, ARB_COST_ESTIMATE],
        mode='lines',
        name='Cost Estimate ($8)',
        line=dict(color='#ff7f0e', width=2, dash='dash')
    ))

    fig.update_layout(
        title="Gross Spread (TTF Converted - HH) vs Cost",
        yaxis_title="USD / MMBtu",
        height=350,
        margin=dict(l=20, r=20, t=40, b=20),
        hovermode="x unified"
    )
    st.plotly_chart(fig, use_container_width=True)
    
    # AI 对套利的简评
    if ai_enabled:
        trend = "Widening" if current_spread > arb_df['Spread'].mean() else "Narrowing"
        st.caption(f"🤖 **AI Strategy Note:** {ai_analyze_market(current_spread, trend)}")

else:
    st.warning("Insufficient data to calculate arbitrage spread (Check HH/TTF feeds).")

st.markdown("---")

# --- ROW 3: Intelligence & News ---
st.markdown("### 3. Market Intelligence")

news_items = get_news_aggregated()
col_news_l, col_news_r = st.columns([1, 1])

# 将新闻分两列展示，节省垂直空间
for i, news in enumerate(news_items):
    target_col = col_news_l if i % 2 == 0 else col_news_r
    with target_col:
        st.markdown(f"""
        <div class="news-item">
            <span style="font-size:0.75em; background:#eee; padding:2px 6px; border-radius:4px;">{news['source']}</span>
            <span style="font-size:0.75em; color:gray;">{news['dt'].strftime('%m-%d %H:%M')}</span><br>
            <a href="{news['link']}" target="_blank" style="text-decoration:none; color:#222; font-weight:600;">{news['title']}</a>
        </div>
        """, unsafe_allow_html=True)

        if ai_enabled:
             # 简单的单条新闻情感分析 (可选，防止 Token 消耗过多)
             pass 

# Footer
st.markdown("<br><div style='text-align:center; color:#ccc; font-size:0.8em;'>Powered by Streamlit, Yahoo Finance & Google Gemini</div>", unsafe_allow_html=True)
