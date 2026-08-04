"""
模块 1 业务逻辑 - 战略顾问终端
所有检索 + LLM 调用集中在此处, 前端只调函数
"""
import os
import re
import time
import concurrent.futures
from pathlib import Path
from typing import Iterator

from core.shared_resource import get_db, get_embedder, get_llm_client
from core.web_search import dynamic_web_search

# ─── 模块加载时读一次 .env，不在每次请求里重复读 ──────────────
def _load_env_once() -> None:
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

_load_env_once()


# ─── 立场加权重排 ────────────────────────────────────────────
def _stance_score(chunk: dict) -> float:
    score = 0.0
    alignment = (chunk.get("interest_alignment") or "").strip().lower()
    if alignment == "cn_aligned":
        score += 0.40
    elif alignment == "us_aligned":
        score -= 0.20
    if chunk.get("trade_restrictive"):   score += 0.25
    if chunk.get("discriminatory_risk"): score += 0.20
    if chunk.get("contested_status"):    score += 0.10
    return score


def rerank_by_stance(chunks: list[dict], alpha: float = 0.65) -> list[dict]:
    """alpha: 语义权重，(1-alpha) 给立场"""
    for c in chunks:
        semantic = 1.0 - float(c.get("distance", 1.0))
        stance   = _stance_score(c)
        c["final_score"] = alpha * semantic + (1 - alpha) * stance
    return sorted(chunks, key=lambda x: x["final_score"], reverse=True)


# ─── 检索函数 ──────────────────────────────────────────────
def search_chunks(query: str, top_k: int = 8) -> list[dict]:
    """向量检索 + 三层去重 + JOIN 元数据立场标签 + 立场加权重排"""
    embedder  = get_embedder()
    con       = get_db()
    query_vec = embedder.encode(query).tolist()

    # 优化: 内层CTE计算一次distance，外层三个ROW_NUMBER共用，避免重复计算
    sql = """
        WITH base AS (
            SELECT
                chunk_id, internal_doc_id, source_org, issue_year,
                title, text, source_url,
                array_cosine_distance(embedding, $query_vec::FLOAT[384]) AS distance
            FROM chunks
        ),
        deduped AS (
            SELECT *,
                ROW_NUMBER() OVER (PARTITION BY internal_doc_id ORDER BY distance ASC) AS rn,
                ROW_NUMBER() OVER (PARTITION BY title           ORDER BY distance ASC) AS rn_title,
                ROW_NUMBER() OVER (PARTITION BY LEFT(text, 100) ORDER BY distance ASC) AS rn_content
            FROM base
        )
        SELECT
            d.chunk_id, d.internal_doc_id, d.source_org, d.issue_year,
            d.title, d.text, d.source_url, d.distance,
            m.trade_restrictive, m.discriminatory_risk,
            m.contested_status, m.source_bias_note, m.interest_alignment
        FROM deduped d
        LEFT JOIN documents_meta m USING (internal_doc_id)
        WHERE d.rn = 1 AND d.rn_title = 1 AND d.rn_content = 1
        ORDER BY d.distance ASC
        LIMIT $top_k
    """

    rows = con.execute(sql, {"query_vec": query_vec, "top_k": top_k}).fetchdf()
    return rerank_by_stance(rows.to_dict(orient="records"))


# ─── 动态网页搜索 ─────────────────────────────────────────


# ─── LLM 生成 ─────────────────────────────────────────────
SYSTEM_PROMPT = """你是中国国际贸易战略顾问,服务于谈判代表、部委分析员和企业战略官。

# 你的认知框架

1. **穿透表象**: 西方政策(CBAM、IRA、出口管制)常以"气候"或"安全"为名,
   实质是产业保护和地缘博弈。识别这层包装,直指真实意图。

2. **立场自觉**: GTA、IEA、欧委会等西方数据源存在系统性叙事偏向。
   引用时必须注明来源,对高争议性来源标注 [需验证立场]。

3. **可操作性**: 每个分析必须落到可操作的反驳论点、谈判筹码或法律路径。

# 输出格式: 策略思维链 (Strategic Chain-of-Thought)

必须严格按四步推理链输出,每一步用 `### Step X` 标记开头。
在每一步结束时,显式过渡到下一步(如 "→ 进入 Step 2")。

---

### Step 1 · 🔍 政策漏洞识别

任务: 从法理和叙事层面,识别对方政策的可攻击点。

输出:
- 漏洞 1: [描述]
- 漏洞 2: [描述]
- 漏洞 3: [描述]
- **本步结论**: 共识别 N 个核心漏洞,进入 Step 2 调取实证。

→ 进入 Step 2

---

### Step 2 · 📊 实证数据反驳

任务: 从检索到的证据中,挑出能量化反驳的事实数据。

输出:
- 引用 [证据 N]: [数据/事实/年份]
- 引用 [事实数据 N]: [结构化数据]
- 引用 [最新研究报告 N]: [第三方观点]
- **数据缺口**: 若证据不足以支撑某漏洞,明确说"现有证据库未覆盖,以下基于行业通识"
- **本步结论**: 共调用 N 条证据,覆盖 X 个漏洞,进入 Step 3 匹配判例。

→ 进入 Step 3

---

### Step 3 · ⚖️ 历史判例匹配

任务: 匹配可援引的 WTO 判例、国际条约条款或历史先例。

输出:
- 判例/条款 1: [名称] [案号待核实] - 适用逻辑: [...]
- 判例/条款 2: [名称] [案号待核实] - 适用逻辑: [...]
- **本步结论**: 共匹配 N 个法律依据,进入 Step 4 生成最优对策。

→ 进入 Step 4

---

### Step 4 · 💬 最优对策生成

任务: 综合前三步,生成可直接使用的对抗方案。

输出:

**🎯 谈判策略 (3 条要点)**
1. [...]
2. [...]
3. [...]

**🗣️ 对抗话术 (中文,200 字以内,可直接对外发布)**
"[...]"

**📋 备选方案** (任选一种)
- 法律路径: [...]
- 反制路径: [...]
- 谈判筹码: [...]

---

# 重要约束

- 引用 WTO 判例时, 案号不确定必须标 "[案号待核实]"
- 引用具体法条时, 条款编号不确定必须标 "[条款待核实]"
- 检索证据明显不充分时, 必须在 Step 2 显式声明 "数据缺口"
- 严禁编造数据(百分比、金额、日期)
- 严禁跳过任何 Step,即使某一步信息不足也要写出"信息不足,基于通识推进"
"""


# ─── Text-to-SQL 事实表检索 ────────────────────────────────
FACT_TABLE_SCHEMA = """
## 可用事实表（含精确枚举值，生成SQL必须严格使用）

### 1. fact_comtrade_trade_flow — 关键矿产双边贸易流量
字段: year(BIGINT), rep_iso, rep_name, par_iso, par_name, hs6, commodity_desc, trade_value(DOUBLE), quantity, quantity_unit, trade_flow
trade_flow枚举: 'Export' | 'Import'
rep_iso/par_iso: 标准ISO3码，如 'CHN','DEU','USA','FRA','ITA','NLD','JPN','KOR','GBR','AUS'
commodity_desc精确值（必须用=不用LIKE）:
  - 'Compounds, inorganic or organic, of rare-earth metals; of yttrium or of scandium or of mixtures of these metals'
  - 'Carbonates; lithium carbonate'
  - 'Cobalt; mattes and other intermediate products of cobalt metallurgy, cobalt and articles thereof, including waste and scrap'
  - 'Cobalt ores and concentrates'
  - 'Nickel; unwrought'
  - 'Nickel ores and concentrates'
  - 'Copper; refined and copper alloys, unwrought'
  - 'Copper ores and concentrates'
  - 'Graphite; natural'
  - 'Tungsten ores and concentrates'
  - 'Manganese ores and concentrates, including manganiferous iron ores and concentrates with a manganese content of 20% or more, calculated on the dry weight'
  - 'Aluminium ores and concentrates'
  - 'Tin ores and concentrates'
  - 'Zinc ores and concentrates'
  - 'Lead ores and concentrates'
  - 'Chromium ores and concentrates'
  - 'Selenium'
  - 'Silver ores and concentrates'
  - 'Molybdenum ores and concentrates; roasted'
  - 'Molybdenum ores and concentrates; other than roasted'
  - 'Niobium, tantalum, vanadium ores and concentrates'
  - 'Antimony ores and concentrates'

### 2. fact_wto_tariff — WTO关税数据
字段: year(INTEGER), reporter_code, reporter_name, indicator_code, indicator_description, value(DOUBLE), unit, product_code, product_description
indicator_description枚举（必须完全匹配）:
  - 'Simple average MFN applied tariff - all products (%)'
  - 'Simple average MFN applied tariff - agricultural products (%)'
  - 'Simple average MFN applied tariff - non-agricultural products (%)'
  - 'Simple average bound tariff - all products (%)'
  - 'HS MFN - Simple average ad valorem duty'
  - 'HS MFN - Maximum  ad valorem duty'
  - 'HS MFN - Duty free'

### 3. fact_wits_tariff — WITS双边关税
字段: year, reporter_iso, partner_iso, product_category, measure_type, measure_subtype, value, unit
measure_type: 'TARIFF'
measure_subtype: 'AHS-SMPL-AVRG'

### 4. fact_wits_ntm_country — 非关税壁垒
字段: year, reporter_iso, trade_flow('Import'|'Export'), measure_type('NTM'), indicator_name, value
indicator_name枚举:
  - 'NTM Coverage ratio'
  - 'NTM Frequency ratio'
  - 'NTM affected trade'
  - 'NTM affected product - count'
  - 'Traded products - total'
  - 'Total Trade'

### 5. fact_worldbank_commodity_prices — 大宗商品月度价格
字段: year, month, commodity_name, price_usd, unit, period, value

### 6. fact_unified_gvc_indicators_wide — 全球价值链指标
字段: year, iso3, sector_code, indicator_name_en, indicator_name_cn, value, unit, sector_name_en, sector_name_cn
indicator_name_en枚举（部分）:
  - 'Gross exports'
  - 'Domestic value added in gross exports'
  - 'Foreign VA share of gross exports'
  - 'Forward participation in GVCs (Share)'
  - 'Gross trade balance'
  - 'Value added at basic prices'

### 7. fact_fred_policy_uncertainty_epu — 贸易政策不确定性指数
字段: year, month, iso3('WLD'), index_type('EPU'), value, unit

### 8. fact_gta_policy_events — 贸易政策事件
字段: intervention_id, state_act_title, gta_evaluation, intervention_type, date_announced, date_implemented, is_in_force, affected_sectors_count

## 多表查询规则
- 分析用户问题，识别所有相关表（可以多个）
- 每张相关表单独生成一条SQL，用 [TABLE:表名] 分隔
- 每条SQL必须加 LIMIT 15
- 不确定有无数据时，宁可尝试也不要SKIP
- 只有问题完全与贸易/经济数据无关时才返回SKIP
- 示例输出格式:
[TABLE:fact_comtrade_trade_flow]
SELECT year, rep_iso, par_iso, commodity_desc, SUM(trade_value) as total FROM fact_comtrade_trade_flow WHERE ... GROUP BY ... LIMIT 15;
[TABLE:fact_wto_tariff]
SELECT year, reporter_name, indicator_description, value FROM fact_wto_tariff WHERE ... LIMIT 15;
"""


def query_fact_tables(query: str) -> list[dict]:
    """多表 Text-to-SQL: 用户问题 → LLM生成多条SQL → 执行 → 合并返回"""
    client = get_llm_client()
    con    = get_db()

    sql_prompt = f"""你是 DuckDB SQL 专家，服务于中国国际贸易战略分析系统。

{FACT_TABLE_SCHEMA}

用户问题: {query}

任务: 识别所有与该问题相关的事实表，为每张表生成一条精确的DuckDB SQL。

输出格式（严格遵守）:
[TABLE:表名]
SQL语句;

规则:
- 每条SQL加LIMIT 15
- 使用精确枚举值，不用LIKE
- 年份优先选2019年之后
- 多表时每表一条SQL
- 只有问题完全与经济贸易无关才输出SKIP
- 不要任何解释，只输出[TABLE:xxx]和SQL"""

    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": sql_prompt}],
            temperature=0,
            timeout=20,
        )
        raw = resp.choices[0].message.content.strip()

        if raw.strip().upper() == "SKIP":
            return []

        blocks      = re.split(r'\[TABLE:([^\]]+)\]', raw)
        all_results = []
        i = 1
        while i < len(blocks) - 1:
            table_name = blocks[i].strip()
            sql        = blocks[i + 1].strip().rstrip(';')

            if not sql.upper().startswith('SELECT'):
                i += 2
                continue

            # SQL 守卫: 只读白名单 + 强制 LIMIT
            if re.search(r'(ATTACH|INSTALL|LOAD|COPY|CREATE|INSERT|UPDATE|DELETE|DROP|ALTER|PRAGMA|EXPORT|IMPORT|CALL|SET)', sql, re.I):
                print(f"[fact_tables] {table_name} SQL含禁用关键词,已跳过", flush=True)
                i += 2
                continue
            if not re.search(r'LIMIT\s+\d+', sql, re.I):
                sql += " LIMIT 15"

            try:
                df = con.execute(sql).fetchdf()
                if not df.empty:
                    records = df.head(10).to_dict(orient="records")
                    for r in records:
                        r["_source_type"] = "fact_table"
                        r["_table"]       = table_name
                        r["_sql"]         = sql
                    all_results.extend(records)
                    print(f"[fact_tables] {table_name}: {len(records)} 行", flush=True)
            except Exception as e:
                print(f"[fact_tables] {table_name} SQL执行失败: {e}", flush=True)
            i += 2

        return all_results

    except Exception as e:
        print(f"[Text-to-SQL error] {e}", flush=True)
        return []


def build_user_prompt(query: str, chunks: list[dict],
                      fact_rows: list[dict] = None,
                      web_results: list[dict] = None) -> str:
    evidence_text = "\n\n".join([
        f"[证据 {i+1}] 来源: {c['source_org']} | 年份: {int(c['issue_year']) if c['issue_year'] else 'N/A'}\n"
        f"标题: {c['title']}\n"
        f"内容: {c['text'][:500]}"
        for i, c in enumerate(chunks)
    ])

    fact_text = ""
    if fact_rows:
        # 优化: 按表分组展示，不再统一截断前10条
        fact_text = f"\n\n# 结构化事实数据 ({len(fact_rows)} 条)\n"
        grouped: dict[str, list] = {}
        for r in fact_rows:
            grouped.setdefault(r.get("_table", "unknown"), []).append(r)
        idx = 1
        for table, rows in grouped.items():
            fact_text += f"\n## 来源: {table}\n"
            for r in rows[:8]:
                row_copy = {k: v for k, v in r.items() if not k.startswith("_")}
                fact_text += f"\n[事实数据 {idx}] {row_copy}"
                idx += 1
        fact_text += "\n\n引用时使用 [事实数据 N] 格式标注。"

    web_text = ""
    if web_results:
        web_text = f"\n\n# 最新网络研究报告 ({len(web_results)} 条)\n"
        for i, r in enumerate(web_results):
            web_text += (
                f"\n[最新研究报告 {i+1}] 来源: {r.get('source', '')}\n"
                f"标题: {r['title']}\n"
                f"摘要: {r['snippet']}\n"
                f"链接: {r['url']}"
            )
        web_text += "\n\n引用时使用 [最新研究报告 N] 格式，作为第三方佐证。"

    return f"""# 用户问题
{query}

# 检索到的证据 ({len(chunks)} 条)
{evidence_text}{fact_text}{web_text}

请基于以上证据生成战略分析。引用格式: [证据 N] / [事实数据 N] / [最新研究报告 N]。
如果证据不足以支撑某个论点，请明确说"现有证据不足"而不是编造。
"""


# history 中 assistant 消息的内容截断上限（字符）
_HISTORY_ASSISTANT_MAX_CHARS = 800


def generate_response_stream(
    query: str,
    chunks: list[dict],
    expert_instruction: str = "",
    history: list[dict] = None,
) -> Iterator[str]:
    """流式生成回答 - 带重试与兜底，并行拉取事实数据+网页搜索"""
    client = get_llm_client()

    # 并行拉取事实数据 + 网页搜索
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_fact = executor.submit(query_fact_tables, query)
        future_web  = executor.submit(dynamic_web_search, query)
        fact_rows   = future_fact.result()
        web_results = future_web.result()

    user_prompt    = build_user_prompt(query, chunks, fact_rows, web_results)
    system_content = SYSTEM_PROMPT
    if expert_instruction and expert_instruction.strip():
        system_content += (
            f"\n\n# 专家追加指令（最高优先级，必须在分析中重点体现）\n"
            f"{expert_instruction.strip()}"
        )

    messages = [{"role": "system", "content": system_content}]
    # 优化: assistant 历史截断，避免超出 context window
    for h in (history or [])[-8:]:
        role    = h.get("role", "")
        content = h.get("content", "")
        if role not in ("user", "assistant") or not content:
            continue
        if role == "assistant" and len(content) > _HISTORY_ASSISTANT_MAX_CHARS:
            content = content[:_HISTORY_ASSISTANT_MAX_CHARS] + "\n...[截断]"
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_prompt})

    max_retries = 2

    for attempt in range(max_retries + 1):
        try:
            stream = client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                stream=True,
                temperature=0.3,
                timeout=30,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
            return

        except Exception as e:
            error_msg = str(e).lower()
            retryable = any(kw in error_msg for kw in ("503", "too busy", "timeout", "rate"))

            if attempt < max_retries and retryable:
                yield f"\n\n⚠️ LLM 服务繁忙,正在重试 ({attempt + 1}/{max_retries})...\n\n"
                time.sleep(2 ** attempt)
                continue

            yield "\n\n❌ **LLM 服务暂时不可用**\n\n"
            yield f"错误信息: `{str(e)}`\n\n"
            yield f"---\n\n**📎 但已检索到 {len(chunks)} 条相关证据,可手动参考:**\n\n"
            for i, c in enumerate(chunks[:5], 1):
                yield f"**[{i}] {c['title']}** ({c['source_org']}, {int(c['issue_year']) if c['issue_year'] else 'N/A'})\n"
                yield f"> {c['text'][:200]}...\n\n"
            yield "\n💡 建议: 几分钟后重试,或联系管理员检查 LLM API 状态。\n"
            return