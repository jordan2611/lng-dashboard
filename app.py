import streamlit as st
import yfinance as yf
import feedparser
import google.generativeai as genai
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
from time import mktime

# ==========================================
# 1. 页面配置与样式
# ==========================================
st.set_page_config(
    page_title="LNG Trading Dashboard Pro",
    page_icon="🚢",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自定义 CSS：增强卡片效果和字体
st.markdown("""
    <style>
    .metric-container {
        background-color: #ffffff;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        border: 1px solid #f0f0f0;
        text-align: center;
    }
    .news-card {
        padding: 15px;
        border-radius: 8px;
        border: 1px solid #e0e0e0;
        margin-bottom: 12px;
        background-color: white;
        transition: transform 0.2s;
    }
    .news-card:hover {
        background-color: #f9f9f9;
        border-color: #ccc;
    }
    .source-tag {
        font-size: 0.75em;
        background-color: #eef;
        color: #44a;
        padding: 2px 6px;
        border-radius: 4px;
        margin-right: 5px;
    }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. Sidebar: 配置
# ==========================================
st.sidebar.title("🚢 LNG Pro Dashboard")
st.sidebar.write("Global Gas Market Intelligence")

api_key = st.sidebar.text_input("Google API Key", type="password", placeholder="Enter Gemini Key for AI Analysis")

ai_enabled = False
if api_key:
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-pro') # 验证初始化
        ai_enabled = True
        st.sidebar.success("✅ AI Engine Active")
    except Exception as e:
        st.sidebar.error(f"❌ API Key Invalid")

st.sidebar.markdown("---")
st.sidebar.markdown("### Data Sources")
st.sidebar.info(
    """
    **Prices:** Yahoo Finance
    - Henry Hub (NG=F)
    - Dutch TTF (TTF=F)
    - JKM (JKM=F)
    
    **News Feeds:**
    - Reuters Energy
    - OilPrice.com
    - LNG Prime
    - Natural Gas Intel
    """
)

# ==========================================
# 3. 核心逻辑函数
# ==========================================

@st.cache_data(ttl=600) # 缓存10分钟
def get_market_data():
    """获取 HH, TTF, JKM 数据"""
    tickers = ['NG=F', 'TTF=F', 'JKM=F']
    
    try:
        # 批量下载数据
        data = yf.download(tickers, period="1mo", group_by='ticker', progress=False)
        
        processed_data = {}
        
        # 辅助函数：安全提取 Close 数据
        def extract_close(ticker_symbol):
            if ticker_symbol in data:
                df = data[ticker_symbol]
                if not df.empty and 'Close' in df.columns:
                    # 移除空值
                    series = df['Close'].dropna()
                    if not series.empty:
                        return series
            return None

        # 1. Henry Hub
        processed_data['HH'] = extract_close('NG=F')
        
        # 2. Dutch TTF
        processed_data['TTF'] = extract_close('TTF=F')
        
        # 3. JKM (经常失败，单独处理逻辑在UI层判断)
        processed_data['JKM'] = extract_close('JKM=F')
        
        return processed_data
        
    except Exception as e:
        st.error(f"Data Feed Connection Error: {e}")
        return {}

def parse_rss_feed():
    """RSS 矩阵抓取与聚合"""
    rss_sources = [
        {"name": "Reuters", "url": "http://feeds.reuters.com/reuters/energyNews"},
        {"name": "OilPrice", "url": "https://oilprice.com/rss/main"},
        {"name": "LNG Prime", "url": "https://lngprime.com/feed/"},
        {"name": "NG Intel", "url": "https://www.naturalgasintel.com/feed/"}
    ]
    
    all_news = []
    
    for source in rss_sources:
        try:
            feed = feedparser.parse(source['url'])
            for entry in feed.entries[:5]: # 每个源只取前5条，避免单个源刷屏
                # 尝试解析时间，不同RSS源时间格式不同
                published_time = datetime.now()
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    published_time = datetime.fromtimestamp(mktime(entry.published_parsed))
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    published_time = datetime.fromtimestamp(mktime(entry.updated_parsed))
                
                all_news.append({
                    "source": source['name'],
                    "title": entry.title,
                    "link": entry.link,
                    "published_dt": published_time,
                    "display_time": published_time.strftime("%Y-%m-%d %H:%M")
                })
        except Exception:
            continue
            
    # 按时间倒序排序 (最新的在最前)
    all_news.sort(key=lambda x: x['published_dt'], reverse=True)
    
    # 只保留前10条
    return all_news[:10]

def analyze_news_ai(title):
    """Gemini AI 分析"""
    if not ai_enabled: return None
    try:
        prompt = f"""
        作为LNG交易专家，分析此标题: "{title}"
        1. 判断方向: Bullish(利多)/Bearish(利空)/Neutral(中性)
        2. 影响力: 1-10分
        3. 一句简短理由 (中文)
        
        格式: [方向] | [分数]/10 | [理由]
        """
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content(prompt)
        return response.text.strip()
    except:
        return None

# ==========================================
# 4. 界面构建
# ==========================================

st.title("🚢 Global LNG Trading Dashboard")
st.markdown("##### 实时跨区域天然气套利监控系统")

# --- Section 1: 价格看板 (3 Columns) ---
market_data = get_market_data()

col1, col2, col3 = st.columns(3)

def display_metric(col, label, series, unit, is_error=False, error_msg=""):
    with col:
        if is_error or series is None:
            st.markdown(f"""
            <div class="metric-container" style="border-left: 5px solid #ccc;">
                <h4 style="margin:0; color:#666;">{label}</h4>
                <p style="color: #d9534f; font-weight: bold; margin-top: 10px;">{error_msg}</p>
            </div>
            """, unsafe_allow_html=True)
        else:
            latest = series.iloc[-1]
            prev = series.iloc[-2] if len(series) > 1 else latest
            delta = latest - prev
            color = "#00c853" if delta >= 0 else "#ff5252" # 绿色涨，红色跌
            
            st.markdown(f"""
            <div class="metric-container" style="border-left: 5px solid {color};">
                <h4 style="margin:0; color:#333;">{label}</h4>
                <h2 style="margin:5px 0;">{unit}{latest:.3f}</h2>
                <p style="color:{color}; margin:0;">{delta:+.3f}</p>
            </div>
            """, unsafe_allow_html=True)

# HH
display_metric(col1, "Henry Hub (US)", market_data.get('HH'), "$")

# TTF
display_metric(col2, "Dutch TTF (EU)", market_data.get('TTF'), "€")

# JKM
# 专门针对 JKM 的逻辑：如果获取不到，显示特定信息
jkm_series = market_data.get('JKM')
if jkm_series is None:
    display_metric(col3, "JKM (Asia)", None, "$", is_error=True, error_msg="数据源缺失 (需付费)")
else:
    display_metric(col3, "JKM (Asia)", jkm_series, "$")

st.markdown("---")

# --- Section 2: 布局 (左侧图表，右侧新闻) ---
chart_col, news_col = st.columns([2, 1], gap="medium")

# --- 左侧: 专业双轴图表 ---
with chart_col:
    st.subheader("📊 跨大西洋价差分析 (HH vs TTF)")
    
    if market_data.get('HH') is not None and market_data.get('TTF') is not None:
        hh_df = market_data['HH']
        ttf_df = market_data['TTF']
        
        # 确保索引对齐（取交集日期）以绘图
        common_index = hh_df.index.intersection(ttf_df.index)
        
        # 创建 Plotly 双轴图
        fig = make_subplots(specs=[[{"secondary_y": True}]])

        # 添加 Henry Hub (左轴)
        fig.add_trace(
            go.Scatter(x=hh_df.index, y=hh_df.values, name="Henry Hub ($/MMBtu)", 
                       line=dict(color='#1f77b4', width=2)),
            secondary_y=False,
        )

        # 添加 TTF (右轴)
        fig.add_trace(
            go.Scatter(x=ttf_df.index, y=ttf_df.values, name="TTF (€/MWh)", 
                       line=dict(color='#ff7f0e', width=2, dash='dot')),
            secondary_y=True,
        )

        # 设置布局
        fig.update_layout(
            height=500,
            title_text="Price Correlation: US vs Europe",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )

        # 设置轴标题
        fig.update_yaxes(title_text="<b>Henry Hub</b> ($/MMBtu)", secondary_y=False, showgrid=True, gridcolor='#eee')
        fig.update_yaxes(title_text="<b>Dutch TTF</b> (€/MWh)", secondary_y=True, showgrid=False)

        st.plotly_chart(fig, use_container_width=True)
        
        st.caption("注：左轴为 HH 价格 (USD)，右轴为 TTF 价格 (EUR)。量级差异较大，故采用双轴对比。")
    else:
        st.warning("等待数据加载以生成图表...")

# --- 右侧: AI 智能情报流 ---
with news_col:
    st.subheader("📰 全球情报矩阵")
    st.write(f"Sources: Reuters, OilPrice, LNG Prime, NG Intel")
    
    with st.spinner("正在聚合多源情报..."):
        news_items = parse_rss_feed()
    
    # 滚动容器
    with st.container(height=600):
        if not news_items:
            st.warning("暂无更新或 RSS 连接超时")
        
        for news in news_items:
            # 判断 AI 分析结果颜色
            ai_result = None
            sentiment_color = "#f0f2f6" # 默认灰色
            
            if ai_enabled:
                ai_text = analyze_news_ai(news['title'])
                if ai_text:
                    if "Bullish" in ai_text: sentiment_color = "#e8f5e9" # 浅绿
                    elif "Bearish" in ai_text: sentiment_color = "#ffebee" # 浅红
                    ai_result = ai_text

            # 渲染卡片
            with st.container():
                st.markdown(f"""
                <div class="news-card" style="border-left: 4px solid #1f77b4;">
                    <div style="margin-bottom: 4px;">
                        <span class="source-tag">{news['source']}</span>
                        <span style="font-size:0.7em; color:grey;">{news['display_time']}</span>
                    </div>
                    <a href="{news['link']}" target="_blank" style="text-decoration:none; color:#2c3e50; font-weight:600;">
                        {news['title']}
                    </a>
                </div>
                """, unsafe_allow_html=True)
                
                if ai_result:
                     st.markdown(f"""
                        <div style="font-size: 0.85em; background-color: {sentiment_color}; padding: 8px; border-radius: 5px; margin-top: -8px; margin-bottom: 15px;">
                            🤖 <b>AI Insight:</b> {ai_result}
                        </div>
                     """, unsafe_allow_html=True)
                else:
                    st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True)
