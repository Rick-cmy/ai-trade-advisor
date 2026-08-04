"""GTSNA 主入口 - 欢迎页"""
import streamlit as st

st.set_page_config(
    page_title="GTSNA 全球贸易战略导航",
    page_icon="🌐",
    layout="wide",
)

from core.theme import apply_theme
apply_theme()

# 先渲染页面内容，再做预热——避免冷启动白屏
st.title("🌐 GTSNA 全球贸易战略导航系统")
st.caption("Global Trade Strategic Navigation Agent — MVP")

st.markdown("""
面向国际谈判代表、部委分析员与企业战略官的**对抗式贸易战略分析系统**：
21 万+文档块向量库 × 贸易事实表 × 实时联网检索，四步推理产出可直接引用的谈判策略与话术。

### 👈 请从左侧侧边栏选择模块

| 模块 | 状态 |
|---|---|
| 💬 战略顾问终端 | ✅ 可用 — 多轮对抗性战略问答 |
| 📊 全球宏观看板 | 🗺️ 路线图 |
| 📈 时序与溢出分析 | 🗺️ 路线图 |
| 🕸️ 稀土网络沙盘 | 🗺️ 路线图 |
""")

st.caption("⚖️ 本系统输出由 AI 基于检索证据生成，仅供决策参考；引用条款与案号请以官方文本核实。")

# Warm-up: 页面渲染完成后预热模型和数据库连接，首次提问免等待
from core.shared_resource import get_embedder, get_db, get_llm_client
with st.spinner("🔥 正在预热模型与数据库（首次启动约半分钟，页面可正常浏览）..."):
    get_embedder()
    get_db()
    get_llm_client()
