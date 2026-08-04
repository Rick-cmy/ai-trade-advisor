"""智库报告风主题 (Policy-Brief theme) — 全局 CSS 注入。

配色: 纸面 #FBFAF6 · 藏蓝 #1E3A5F · 绛红 #8C2F39 · 墨色 #22303F
用法: 在每个页面 st.set_page_config() 之后调用 apply_theme()。
"""
import streamlit as st

_CSS = """
<style>
:root {
  --paper: #FBFAF6;
  --paper-2: #F3EFE4;
  --footnote: #F6F3EA;
  --ink: #22303F;
  --navy: #1E3A5F;
  --burgundy: #8C2F39;
  --line: #E3DFD3;
  --muted: #5A6878;
}

.stApp { background: var(--paper); }

/* ── 报告式标题：衬线 + 藏蓝 ───────────────────────────── */
h1, h2, h3 {
  font-family: Georgia, "Songti SC", "Noto Serif SC", "SimSun", serif !important;
  color: var(--navy) !important;
  letter-spacing: 0.01em;
}
h1 { border-bottom: 2px solid var(--navy); padding-bottom: 0.35rem; }
h3 { border-left: 4px solid var(--burgundy); padding-left: 0.6rem; }

[data-testid="stCaptionContainer"] { color: var(--muted) !important; }

/* ── 侧边栏：浅纸面 ───────────────────────────────────── */
[data-testid="stSidebar"] {
  background: var(--paper-2);
  border-right: 1px solid var(--line);
}
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 { border: none; padding-left: 0; }

/* ── 对话气泡：白卡片；用户消息带绛红侧标 ───────────────── */
[data-testid="stChatMessage"] {
  background: #FFFFFF;
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 1rem 1.2rem;
  box-shadow: 0 1px 2px rgba(30, 58, 95, 0.05);
}
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
  background: var(--paper-2);
  border-left: 3px solid var(--burgundy);
}

/* ── 输入框 ──────────────────────────────────────────── */
[data-testid="stChatInput"] textarea { background: #FFFFFF; }

/* ── 证据脚注区 (expander) ────────────────────────────── */
[data-testid="stExpander"] {
  background: var(--footnote);
  border: 1px solid var(--line);
  border-radius: 3px;
}

/* ── 话术引用块 ──────────────────────────────────────── */
blockquote {
  border-left: 3px solid var(--burgundy) !important;
  background: var(--footnote);
  padding: 0.5rem 1rem;
}

/* ── Markdown 表格：简报表样式 ────────────────────────── */
table { border-collapse: collapse; }
table th { background: var(--paper-2); color: var(--navy); }
table th, table td { border: 1px solid var(--line) !important; padding: 0.4rem 0.8rem; }

/* ── 按钮：藏蓝描边 ──────────────────────────────────── */
.stButton button {
  border: 1px solid var(--navy);
  color: var(--navy);
  background: #FFFFFF;
  border-radius: 3px;
}
.stButton button:hover {
  background: var(--navy);
  color: #FFFFFF;
  border-color: var(--navy);
}

hr { border-color: var(--line); }
</style>
"""


def apply_theme() -> None:
    """注入智库报告风全局样式。"""
    st.markdown(_CSS, unsafe_allow_html=True)
