"""模块 1: 交互式战略顾问终端"""
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

from core.logic_mod1 import search_chunks, generate_response_stream

st.set_page_config(page_title="战略顾问终端", page_icon="💬", layout="wide")

from core.theme import apply_theme
apply_theme()

# ─── 常量 ──────────────────────────────────────────────────
DATA_DIR  = Path.home() / ".gtsna"
HIST_FILE = DATA_DIR / "history_mod1.json"
LOG_FILE  = DATA_DIR / "usage.log"

EXAMPLE_QUESTIONS = [
    "中东近期对中方出口政策变化",
    "欧盟碳边境调节机制（CBAM）对中国钢铁出口的冲击与应对",
    "若美国扩大半导体设备对华出口管制，中方在 WTO 框架内有哪些反制路径？",
]

DISCLAIMER = "本系统输出由 AI 基于检索证据生成，仅供决策参考；引用条款与案号请以官方文本核实。"


# ─── 轻量运行日志 ──────────────────────────────────────────
@st.cache_resource
def _get_logger() -> logging.Logger:
    DATA_DIR.mkdir(exist_ok=True)
    logger = logging.getLogger("gtsna.usage")
    if not logger.handlers:
        handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


# ─── 对话持久化（失败不阻断主流程）────────────────────────────
def _load_history() -> list[dict]:
    try:
        return json.loads(HIST_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_history(msgs: list[dict]) -> None:
    try:
        DATA_DIR.mkdir(exist_ok=True)
        HIST_FILE.write_text(
            json.dumps(msgs, ensure_ascii=False, default=str), encoding="utf-8"
        )
    except Exception:
        pass


# ─── 检索缓存：相同问题+参数 1 小时内直接复用 ────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _cached_search(query: str, top_k: int) -> list[dict]:
    return search_chunks(query, top_k=top_k)


# ─── 渲染工具 ──────────────────────────────────────────────
def _render_stance_badge(chunk: dict) -> str:
    """生成立场徽章字符串"""
    alignment = (chunk.get("interest_alignment") or "neutral").strip().lower()
    parts = []

    if alignment == "cn_aligned":
        parts.append("🟢 中方有利")
    elif alignment == "us_aligned":
        parts.append("🔴 中方不利")
    else:
        parts.append("🟡 中立")

    if chunk.get("trade_restrictive"):   parts.append("⚠️ 贸易限制")
    if chunk.get("discriminatory_risk"): parts.append("🚨 歧视风险")
    if chunk.get("contested_status"):    parts.append("⚖️ 争议")
    if chunk.get("source_bias_note"):    parts.append("📌 需验证立场")

    if chunk.get("final_score"):
        parts.append(f"📊 相关度 {chunk['final_score']:.2f}")

    return "  ".join(parts)


def _mark_pending(md: str) -> str:
    """[条款待核实]/[案号待核实] → 琥珀徽章"""
    return re.sub(
        r"\[(条款待核实|案号待核实|待核实)\]",
        r'<span class="pending-badge">\1</span>',
        md,
    )


def _split_analysis(content: str) -> tuple[str, str]:
    """在 Step 4 标题处切分：(推理过程, 结论部分)。找不到则全部视为结论。"""
    m = re.search(r"^#{0,4}\s*Step\s*4", content, flags=re.M)
    if not m:
        return "", content
    return content[: m.start()], content[m.start():]


def _extract_key_points(content: str) -> list[str]:
    """从分析全文提取要点：漏洞标题 + 判例名 + 首选策略"""
    points = []
    for num, title in re.findall(r"漏洞\s*(\d+)\s*[:：]\s*([^。\n（(]{4,32})", content)[:3]:
        points.append(f"**漏洞 {num}** · {title.strip('*# ')}")
    cases = re.findall(r"[“\"]([^”\"]{2,18}案)[”\"]", content)
    if cases:
        points.append("**可援判例** · " + "、".join(dict.fromkeys(cases))[:60])
    _, step4 = _split_analysis(content)
    strategies = re.findall(r"^\s*1\.\s*\*{0,2}([^：:*\n]{4,30})[：:]", step4, flags=re.M)
    if strategies:
        points.append(f"**首选策略** · {strategies[0].strip()}")
    return points


def _brief_markdown(question: str, msg: dict, issue_no: int) -> str:
    """把单轮问答打包成可下载的 Markdown 简报"""
    lines = [
        f"# GTSNA 战略简报 · 第 {issue_no} 期",
        f"\n> 生成时间：{msg.get('ts', '')} · {DISCLAIMER}",
        f"\n## 问题\n\n{question}",
        f"\n## 分析\n\n{msg['content']}",
    ]
    if msg.get("evidence"):
        lines.append("\n## 引用证据\n")
        for i, ev in enumerate(msg["evidence"]):
            year = ev.get("issue_year")
            year = int(year) if year else "N/A"
            lines.append(f"{i+1}. **{ev.get('title','')}** — {ev.get('source_org','')} · {year}")
            if ev.get("source_url"):
                lines.append(f"   <{ev['source_url']}>")
    return "\n".join(lines)


def _render_user(msg: dict) -> None:
    with st.chat_message("user"):
        st.markdown('<div class="q-eyebrow">问题</div>', unsafe_allow_html=True)
        st.markdown(msg["content"])


def _render_assistant(msg: dict, idx: int, question: str, issue_no: int,
                      show_evidence: bool, is_latest: bool) -> None:
    with st.chat_message("assistant"):
        header = f"GTSNA 简报 · 第 {issue_no} 期 · {msg.get('ts', '')}"
        if msg.get("expert_used"):
            header += " · 🎯 已应用专家指令"
        st.caption(header)

        content = msg["content"]
        reasoning, conclusion = _split_analysis(content)

        # 本期要点（结论前置）
        points = _extract_key_points(content)
        if points:
            st.markdown(
                '<div class="key-card"><div class="key-title">📌 本期要点</div>\n\n'
                + "\n".join(f"- {p}" for p in points)
                + "</div>",
                unsafe_allow_html=True,
            )

        if reasoning:
            with st.expander("🔎 完整推理过程（Step 1–3：漏洞识别 · 实证反驳 · 判例匹配）"):
                st.markdown(_mark_pending(reasoning), unsafe_allow_html=True)
            st.markdown(_mark_pending(conclusion), unsafe_allow_html=True)
        else:
            st.markdown(_mark_pending(content), unsafe_allow_html=True)

        # 证据脚注
        if show_evidence and msg.get("evidence"):
            with st.expander(f"📎 引用证据 ({len(msg['evidence'])} 条)"):
                for i, ev in enumerate(msg["evidence"]):
                    year = ev.get("issue_year")
                    year = int(year) if year else "N/A"
                    st.markdown(f"**[{i+1}]** `{ev.get('source_org','')}` · {year}")
                    st.markdown(f"📄 *{ev.get('title','')}*")
                    st.caption(_render_stance_badge(ev))
                    st.caption(str(ev.get("text", ""))[:300] + "...")
                    if ev.get("source_url"):
                        st.markdown(f"[🔗 原文链接]({ev['source_url']})")
                    st.divider()

        # 下载本期简报
        st.download_button(
            "⬇ 下载本期简报 (Markdown)",
            data=_brief_markdown(question, msg, issue_no),
            file_name=f"GTSNA_brief_{issue_no:03d}.md",
            mime="text/markdown",
            key=f"dl_{idx}",
        )

        # 建议追问（仅最新一轮）
        if is_latest:
            topics = re.findall(r"漏洞\s*\d+\s*[:：]\s*([^。\n（(]{4,24})", content)[:3]
            if topics:
                st.caption("建议追问")
                cols = st.columns(len(topics))
                for c, t in zip(cols, topics):
                    t = t.strip("*# ")
                    if c.button(f"深挖：{t}", key=f"fu_{idx}_{t[:8]}"):
                        st.session_state.mod1_pending = (
                            f"请针对「{t}」深度展开：需要补充哪些证据、可执行动作清单、以及主要风险点。"
                        )
                        st.rerun()


# ─── 页面 ──────────────────────────────────────────────────
st.title("💬 交互式战略顾问终端")
st.caption("适用对象: 国际谈判代表 · 部委行业分析员 · 企业高级战略官")

if "mod1_messages" not in st.session_state:
    st.session_state.mod1_messages = _load_history()

# ─── 侧边栏 ────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 配置")
    top_k = st.slider("检索证据数", 4, 12, 8, help="每轮从 21 万+文档块中检索的证据条数；越多越全面，越少越聚焦")
    show_evidence = st.toggle("显示证据卡片", value=True)

    st.divider()
    st.subheader("🎯 专家介入")
    expert_instruction = st.text_area(
        "追加分析指令",
        placeholder="例如：请强化「共同但有区别的责任」原则在环境贸易中的适用性论证",
        help="输入后下一次提问时生效，专家指令将覆盖当前分析方向",
    )
    if expert_instruction:
        st.caption("✅ 指令已就绪，下次提问时生效")

    st.divider()
    if st.session_state.mod1_messages:
        transcript = "\n\n---\n\n".join(
            ("**问题**：" if m["role"] == "user" else "") + m["content"]
            for m in st.session_state.mod1_messages
        )
        st.download_button(
            "📄 导出全部对话",
            data=f"# GTSNA 战略顾问对话记录\n\n{transcript}",
            file_name="GTSNA_conversation.md",
            mime="text/markdown",
        )
    with st.popover("🗑️ 清空对话"):
        st.markdown("确认清空全部对话？此操作不可恢复。")
        if st.button("确认清空", type="primary"):
            st.session_state.mod1_messages = []
            _save_history([])
            st.rerun()

# ─── 空状态：欢迎卡 + 示例问题 ───────────────────────────────
if not st.session_state.mod1_messages:
    st.markdown(
        '<div class="welcome-card">本终端针对你的战略问题执行四步对抗式分析：'
        "<b>漏洞识别 → 实证反驳 → 判例匹配 → 对策生成</b>，"
        "每条结论均锚定检索证据与 WTO 判例，并产出可直接引用的谈判话术。</div>",
        unsafe_allow_html=True,
    )
    st.caption("试试这些问题：")
    for i, q in enumerate(EXAMPLE_QUESTIONS):
        if st.button(q, key=f"ex_{i}"):
            st.session_state.mod1_pending = q
            st.rerun()

# ─── 渲染历史消息 ──────────────────────────────────────────
msgs = st.session_state.mod1_messages
last_assistant_idx = max(
    (i for i, m in enumerate(msgs) if m["role"] == "assistant"), default=-1
)
issue_no = 0
for i, m in enumerate(msgs):
    if m["role"] == "user":
        _render_user(m)
    else:
        issue_no += 1
        question = msgs[i - 1]["content"] if i > 0 and msgs[i - 1]["role"] == "user" else ""
        _render_assistant(
            m, i, question, issue_no, show_evidence, is_latest=(i == last_assistant_idx)
        )

# ─── 输入（打字 or 示例/追问按钮）───────────────────────────
typed = st.chat_input("请输入您的战略问题...")
user_input = typed or st.session_state.pop("mod1_pending", None)
if user_input:
    st.session_state.mod1_messages.append(
        {"role": "user", "content": user_input, "ts": datetime.now().strftime("%Y-%m-%d %H:%M")}
    )
    _save_history(st.session_state.mod1_messages)
    st.rerun()

# ─── 生成：最后一条是未回答的问题时执行 ───────────────────────
if msgs and msgs[-1]["role"] == "user":
    pending_q = msgs[-1]["content"]
    with st.chat_message("assistant"):
        try:
            t0 = time.time()
            with st.status("🔍 正在检索证据...", expanded=False) as status:
                chunks = _cached_search(pending_q, top_k)
                t_search = time.time() - t0
                status.update(
                    label=f"✅ 已检索 {len(chunks)} 条证据 · {t_search:.1f}s（向量库 + 事实表 + 联网并行）",
                    state="complete",
                )

            t1 = time.time()
            with st.spinner("🤖 正在生成战略分析..."):
                full_response = st.write_stream(
                    generate_response_stream(
                        pending_q, chunks, expert_instruction,
                        history=st.session_state.mod1_messages,
                    )
                )
            t_gen = time.time() - t1

            if not str(full_response).strip():
                raise RuntimeError("LLM 返回空响应")

            st.session_state.mod1_messages.append({
                "role": "assistant",
                "content": str(full_response),
                "evidence": chunks,
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "expert_used": bool(expert_instruction and expert_instruction.strip()),
            })
            _save_history(st.session_state.mod1_messages)
            _get_logger().info(
                "q_len=%d n_chunks=%d t_search=%.1fs t_gen=%.1fs",
                len(pending_q), len(chunks), t_search, t_gen,
            )
            st.rerun()

        except Exception as e:
            st.error(f"分析未完成：{e}。问题已保留，可直接重试。")
            if st.button("🔄 重试本次分析"):
                st.rerun()

st.caption(f"⚖️ {DISCLAIMER}")
