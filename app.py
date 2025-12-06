import streamlit as st

# 设置页面配置（宽屏模式，深色主题）
st.set_page_config(layout="wide", page_title="TradeReview AI", page_icon="📈")

st.title("🚀 TradeReview AI - 启动中...")
st.success("环境配置成功！你可以开始构建你的交易复盘系统了。")

# 侧边栏模拟
with st.sidebar:
    st.header("账户设置")
    st.info("这里未来将用来输入 API Key")

