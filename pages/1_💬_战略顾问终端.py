"""模块 1: 交互式战略顾问终端"""
import streamlit as st
from core.logic_mod1 import search_chunks, generate_response_stream
def _render_stance_badge(chunk: dict) -> str:
    """生成立场徽章字符串"""
    alignment = (chunk.get("interest_alignment") or "neutral").strip().lower()
    parts = []

    # 立场颜色
    if alignment == "cn_aligned":
        parts.append("🟢 中方有利")
    elif alignment == "us_aligned":
        parts.append("🔴 中方不利")
    else:
        parts.append("🟡 中立")

    # 风险标签
    if chunk.get("trade_restrictive"):   parts.append("⚠️ 贸易限制")
    if chunk.get("discriminatory_risk"): parts.append("🚨 歧视风险")
    if chunk.get("contested_status"):    parts.append("⚖️ 争议")
    if chunk.get("source_bias_note"):    parts.append("📌 需验证立场")

    # 相关性分数
    if chunk.get("final_score"):
        parts.append(f"📊 相关度 {chunk['final_score']:.2f}")

    return "  ".join(parts)

st.set_page_config(page_title="战略顾问终端", page_icon="💬", layout="wide")

st.title("💬 交互式战略顾问终端")
st.caption("适用对象: 国际谈判代表 · 部委行业分析员 · 企业高级战略官")

# ─── 初始化 session state (必须带 mod1_ 前缀避免与其他模块冲突) ───
if "mod1_messages" not in st.session_state:
    st.session_state.mod1_messages = []

# ─── 侧边栏 ────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 配置")
    top_k = st.slider("检索证据数", 4, 12, 8)
    show_evidence = st.toggle("显示证据卡片", value=True)
    
    st.divider()
    st.subheader("🎯 专家介入")
    expert_instruction = st.text_area(
        "追加分析指令",
        placeholder="例如：请强化「共同但有区别的责任」原则在环境贸易中的适用性论证",
        help="输入后下一次提问时生效，专家指令将覆盖当前分析方向"
    )
    if expert_instruction:
        st.caption("✅ 指令已就绪，下次提问时生效")
    
    if st.button("🗑️ 清空对话"):
        st.session_state.mod1_messages = []
        st.rerun()


# ─── 渲染历史消息 ──────────────────────────────────────────
for msg in st.session_state.mod1_messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        # 如果是助手消息且带证据, 展示证据
        if msg["role"] == "assistant" and msg.get("evidence") and show_evidence:
            with st.expander(f"📎 引用证据 ({len(msg['evidence'])} 条)"):
                for i, ev in enumerate(msg["evidence"]):
                    st.markdown(f"**[{i+1}]** `{ev['source_org']}` · {int(ev['issue_year']) if ev['issue_year'] else 'N/A'}")
                    st.markdown(f"📄 *{ev['title']}*")
                    st.caption(_render_stance_badge(ev))
                    st.caption(ev['text'][:300] + "...")
                    if ev.get('source_url'):
                        st.markdown(f"[🔗 原文链接]({ev['source_url']})")
                    st.divider()

# ─── 用户输入 ──────────────────────────────────────────────
if user_input := st.chat_input("请输入您的战略问题..."):

    # 立即显示用户消息
    st.session_state.mod1_messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # 助手响应
    with st.chat_message("assistant"):

        # 第一步: 检索
        with st.status("🔍 正在检索证据...", expanded=False) as status:
            chunks = search_chunks(user_input, top_k=top_k)
            status.update(label=f"✅ 已检索 {len(chunks)} 条证据", state="complete")

        # 第二步: 流式生成 ← 替换这整段
        with st.spinner("🤖 正在生成战略分析..."):
            full_response = st.write_stream(
                generate_response_stream(
                    user_input, chunks, expert_instruction,
                    history=st.session_state.mod1_messages
                )
            )
        if not full_response.strip():
            full_response = "⚠️ LLM 返回空响应,请检查 API Key 或网络连接。"
        
        # 第三步: 渲染证据卡片
        if show_evidence and chunks:
            with st.expander(f"📎 引用证据 ({len(chunks)} 条)"):
                for i, ev in enumerate(chunks):
                    st.markdown(f"**[{i+1}]** `{ev['source_org']}` · {int(ev['issue_year']) if ev['issue_year'] else 'N/A'}")
                    st.markdown(f"📄 *{ev['title']}*")
                    st.caption(_render_stance_badge(ev))
                    st.caption(ev['text'][:300] + "...")
                    if ev.get('source_url'):
                        st.markdown(f"[🔗 原文链接]({ev['source_url']})")
                    st.divider()

        # 存到历史
        st.session_state.mod1_messages.append({
            "role": "assistant",
            "content": full_response,
            "evidence": chunks,
        })
