import streamlit as st
import yfinance as yf
import feedparser
import google.generativeai as genai
import pandas as pd
from datetime import datetime

# ==========================================
# 1. 页面配置与样式
# ==========================================
st.set_page_config(
    page_title="LNG Trading Dashboard",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自定义 CSS 以优化界面显得更专业
st.markdown("""
    <style>
    .metric-card {
        background-color: #f0f2f6;
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 10px;
        border-left: 5px solid #ff4b4b;
    }
    .news-card {
        padding: 15px;
        border-radius: 8px;
        border: 1px solid #e0e0e0;
        margin-bottom: 15px;
        background-color: white;
    }
    .ai-badge-bull { background-color: #d4edda; color: #155724; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 0.8em; }
    .ai-badge-bear { background-color: #f8d7da; color: #721c24; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 0.8em; }
    .ai-badge-neutral { background-color: #e2e3e5; color: #383d41; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 0.8em; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. Sidebar: API Key 配置
# ==========================================
st.sidebar.title("⚙️ 设置")
st.sidebar.write("请输入您的 Google Gemini API Key 以解锁 AI 智能分析功能。")

api_key = st.sidebar.text_input("Google API Key", type="password", placeholder="Paste your AI Studio key here")

ai_enabled = False
if api_key:
    try:
        genai.configure(api_key=api_key)
        # 简单测试一下 Key 是否有效
        model = genai.GenerativeModel('gemini-pro')
        ai_enabled = True
        st.sidebar.success("✅ AI 引擎已就绪")
    except Exception as e:
        st.sidebar.error(f"❌ API Key 无效: {e}")
else:
    st.sidebar.warning("⚠️ 未检测到 API Key，AI 分析功能已禁用。")

st.sidebar.markdown("---")
st.sidebar.info("数据来源:\n- Price: Yahoo Finance\n- News: OilPrice.com / Reuters")

# ==========================================
# 3. 核心功能函数
# ==========================================

@st.cache_data(ttl=300) # 缓存5分钟
def get_price_data():
    """获取 NG=F 和 TTF=F 的最近1个月数据"""
    tickers = ['NG=F', 'TTF=F']
    try:
        # 批量下载
        data = yf.download(tickers, period="1mo", group_by='ticker', progress=False)
        
        # 处理数据结构
        result = {}
        
        # 处理 Henry Hub (NG=F)
        if not data.empty and 'NG=F' in data:
            ng_data = data['NG=F']['Close']
            result['Henry Hub (USD/MMBtu)'] = ng_data
        elif not data.empty and 'Close' in data: 
            # 如果只下载到一个，结构可能不同
            result['Henry Hub (USD/MMBtu)'] = data['Close']
            
        # 处理 TTF (TTF=F) - Yahoo Finance 上 TTF 经常不稳定
        if not data.empty and 'TTF=F' in data:
            ttf_data = data['TTF=F']['Close']
            # TTF 在 Yahoo 上通常是 EUR/MWh，这里简单展示原始值，不做汇率转换以保持纯粹
            result['Dutch TTF (EUR/MWh)'] = ttf_data
            
        return pd.DataFrame(result)
    except Exception as e:
        st.error(f"数据获取失败: {e}")
        return pd.DataFrame()

def get_news_feed():
    """获取能源新闻 RSS"""
    # 备选源列表，因为 RSS 源经常变动
    rss_urls = [
        "https://oilprice.com/rss/category/energy/natural-gas",
        "http://feeds.reuters.com/reuters/energyNews" 
    ]
    
    news_items = []
    
    for url in rss_urls:
        try:
            feed = feedparser.parse(url)
            if feed.entries:
                # 只取前5条
                for entry in feed.entries[:5]:
                    news_items.append({
                        "title": entry.title,
                        "link": entry.link,
                        "published": entry.get("published", datetime.now().strftime("%Y-%m-%d"))
                    })
                break # 如果第一个源成功，就跳出
        except Exception:
            continue
            
    return news_items

def analyze_news_with_ai(news_title):
    """调用 Gemini Pro 分析新闻"""
    if not ai_enabled:
        return None
    
    try:
        prompt = f"""
        作为资深LNG交易员，请分析以下新闻标题。
        新闻标题: "{news_title}"
        
        任务:
        1. 判断对天然气价格是 利多(Bullish)、利空(Bearish) 还是 中性(Neutral)。
        2. 给出影响力打分 (1-10)。
        3. 用一句话解释原因。
        
        请严格按照此格式输出:
        Sentiment: [Bullish/Bearish/Neutral] | Score: [1-10] | Reason: [你的分析]
        """
        
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"AI 分析暂时不可用: {str(e)}"

# ==========================================
# 4. 主界面布局
# ==========================================

st.title("🔥 LNG Trading Dashboard")
st.markdown("全球液化天然气市场实时监控与 AI 辅助决策系统")

# 创建两栏布局
col1, col2 = st.columns([3, 2], gap="large")

# --- 左侧: 市场概览 ---
with col1:
    st.subheader("📈 市场概览 (Price Action)")
    
    with st.spinner('正在加载市场数据...'):
        df_prices = get_price_data()
    
    if not df_prices.empty:
        # 显示最新价格指标
        m_col1, m_col2 = st.columns(2)
        
        # Henry Hub Metric
        if 'Henry Hub (USD/MMBtu)' in df_prices.columns:
            hh_series = df_prices['Henry Hub (USD/MMBtu)'].dropna()
            if not hh_series.empty:
                latest_hh = hh_series.iloc[-1]
                prev_hh = hh_series.iloc[-2] if len(hh_series) > 1 else latest_hh
                delta_hh = latest_hh - prev_hh
                m_col1.metric("Henry Hub (NG=F)", f"${latest_hh:.3f}", f"{delta_hh:.3f}")

        # TTF Metric
        if 'Dutch TTF (EUR/MWh)' in df_prices.columns:
            ttf_series = df_prices['Dutch TTF (EUR/MWh)'].dropna()
            if not ttf_series.empty:
                latest_ttf = ttf_series.iloc[-1]
                prev_ttf = ttf_series.iloc[-2] if len(ttf_series) > 1 else latest_ttf
                delta_ttf = latest_ttf - prev_ttf
                m_col2.metric("Dutch TTF (EUR/MWh)", f"€{latest_ttf:.3f}", f"{delta_ttf:.3f}")
        
        # 绘制图表
        st.markdown("##### 30天价格走势")
        st.line_chart(df_prices)
    else:
        st.warning("暂无法获取市场价格数据，请稍后重试。")

# --- 右侧: AI 智能情报局 ---
with col2:
    st.subheader("🤖 AI 智能情报局")
    st.markdown("_基于 Gemini Pro 实时分析市场情绪_")
    
    with st.spinner('正在获取最新能源新闻...'):
        news_list = get_news_feed()
    
    if not news_list:
        st.info("暂无最新新闻或RSS源连接超时。")
    
    for news in news_list:
        with st.container():
            # 外层容器样式
            st.markdown(f"""
            <div class="news-card">
                <a href="{news['link']}" target="_blank" style="text-decoration:none; color:#1f77b4; font-weight:bold; font-size:1.1em;">
                    {news['title']}
                </a>
                <div style="font-size:0.8em; color:gray; margin-top:5px;">📅 {news['published']}</div>
            </div>
            """, unsafe_allow_html=True)
            
            # AI 分析部分
            if ai_enabled:
                with st.status(f"AI 分析中...", expanded=False) as status:
                    analysis = analyze_news_with_ai(news['title'])
                    status.update(label="AI 分析完成", state="complete", expanded=True)
                    
                    if analysis:
                        # 解析简单的格式
                        if "Bullish" in analysis:
                            badge_class = "ai-badge-bull"
                            icon = "🐂"
                        elif "Bearish" in analysis:
                            badge_class = "ai-badge-bear"
                            icon = "🐻"
                        else:
                            badge_class = "ai-badge-neutral"
                            icon = "⚖️"
                            
                        st.markdown(f"""
                        <div style="margin-top: -10px; margin-bottom: 20px; padding-left: 5px;">
                            <span class="{badge_class}">{icon} {analysis}</span>
                        </div>
                        """, unsafe_allow_html=True)
            elif not ai_enabled:
                st.caption("🔒 输入 API Key 以查看对此新闻的 AI 交易分析")
            
            st.markdown("---")

# ==========================================
# Footer
# ==========================================
st.markdown(
    """
    <div style='text-align: center; color: grey; font-size: 0.8em; margin-top: 50px;'>
        LNG Trading Dashboard v1.0 | Built with Python & Streamlit
    </div>
    """, 
    unsafe_allow_html=True
)
