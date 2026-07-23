"""
共享资源层 - 所有模块通过这里访问数据库和模型
切记: 不要在 pages/X.py 里直接 duckdb.connect()
"""
import os
from pathlib import Path
from functools import lru_cache

import duckdb
import streamlit as st
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from openai import OpenAI

load_dotenv()

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "db_workspace/gtsna.duckdb"


@st.cache_resource
def get_db():
    """
    DuckDB 连接 (只读, 全局唯一)
    用 @st.cache_resource 保证多页应用切换时不重复连接
    """
    con = duckdb.connect(str(DB_PATH), read_only=True)
    con.execute("LOAD vss;")
    return con


@st.cache_resource
def get_embedder():
    """
    嵌入模型 (全局唯一, 启动时只加载一次)
    """
    return SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')


@st.cache_resource
def get_llm_client():
    """
    LLM 客户端 (DeepSeek, 兼容 OpenAI SDK)
    """
    return OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",
    )
