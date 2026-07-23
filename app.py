"""GTSNA 主入口 - 欢迎页"""
import streamlit as st

# Warm-up: 启动时预热模型和数据库连接,避免用户第一次点击时长时间等待
from core.shared_resource import get_embedder, get_db, get_llm_client
with st.spinner("🔥 系统启动中,正在预热模型和数据库..."):
    get_embedder()
    get_db()
    get_llm_client()
st.set_page_config(
    page_title="GTSNA 全球贸易战略导航",
    page_icon="🌐",
    layout="wide",
)

st.title("🌐 GTSNA 全球贸易战略导航系统")
st.caption("Global Trade Strategic Navigation Agent — MVP")

st.markdown("""
### 👈 请从左侧侧边栏选择模块

| 模块 | 功能 |
|---|---|
| 💬 战略顾问终端 | 多轮对抗性战略问答 |
| 📊 全球宏观看板 | (开发中) |
| 📈 时序与溢出分析 | (开发中) |
| 🕸️ 稀土网络沙盘 | (开发中) |
""")
