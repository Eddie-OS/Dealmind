"""Handbook Analysis v2 · 关键链路烟雾测试

验证两件事：
1. 创建会话/批量时可传 handbook_id → 落库 + API 返回体透出
2. 会话启动时 _build_handbook_block 渲染出来的 Markdown 块
   真的包含 1/3/3/5/9/10 关键标签（卖点/竞品/参数/FAQ/演示）

不真正跑 LLM，因此完全离线、不消耗任何 token。
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

from fastapi.testclient import TestClient

from src.api.server import app
from src.schema import (
    DialogueState,
    JudgeFeedback,
    PersonaProfile,
    PressureProfile,
    SessionMemory,
)
from src.agents import _build_handbook_block
from src.storage import db as storage_db


logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("smoke_v2")


def _check(cond: bool, msg: str) -> None:
    if cond:
        logger.info("OK   %s", msg)
    else:
        logger.error("FAIL %s", msg)
        sys.exit(2)


def _make_state(handbook_id: int | None) -> DialogueState:
    persona = PersonaProfile(
        id="p_smoke",
        name="测试客户",
        personality="—",
        pain_points=[],
        objection_style="—",
        purchase_goal="—",
        pressure_profile=PressureProfile(
            price_sensitivity=0.5, trust_threshold=0.5, patience=0.5,
            competitor_awareness=0.5, decision_power=0.5,
            emotion_volatility=0.5, need_urgency=0.5,
            skepticism=0.5, bargaining_aggressiveness=0.5,
        ),
    )
    return DialogueState(
        session_id="sess_smoke",
        topic="MatePad 销售模拟",
        product_text="",
        persona_profile=persona,
        round_idx=0,
        max_rounds=10,
        session_memory=SessionMemory.empty(),
        judge_feedback=JudgeFeedback.empty(),
        handbook_id=handbook_id,
    )


def main() -> None:
    # ---- A) _build_handbook_block 直接调，确认渲染 ----
    logger.info("=== A) _build_handbook_block 直接渲染测试 ===")
    with storage_db.connection_scope() as conn:
        storage_db.init_schema(conn)
        hbs = storage_db.list_handbooks(conn, status="ready")
    _check(len(hbs) >= 1, f"全库 ready handbook >= 1，实际 {len(hbs)}")
    hb_id = hbs[0]["id"]
    logger.info("  seeded handbook id=%s name=%s", hb_id, hbs[0]["name"])

    # 测试 1：显式绑定
    state = _make_state(handbook_id=hb_id)
    block = _build_handbook_block(state)
    expects = [
        "产品手册：",                              # 头部
        "本场对话的**销冠剧本**",                  # 强约束语
        "三大核心卖点",                            # ③
        "三大竞品差异",                            # ③
        "五大核心参数",                            # ⑤
        "九大 FAQ",                                # ⑨
        "十大演示动作",                            # ⑩
        "必须",
        "严禁说手册明确否定/未授权的内容",
    ]
    missing = [e for e in expects if e not in block]
    _check(not missing, f"显式 handbook_id 块完整，缺：{missing}")
    snippet = block[:120].encode("ascii", "replace").decode()
    logger.info("  block head: %s", snippet)
    logger.info("  block 总长 = %d 字符", len(block))

    # 测试 2：handbook_id=None 时自动套用（库里就一份 ready）
    state2 = _make_state(handbook_id=None)
    block2 = _build_handbook_block(state2)
    _check(
        "三大核心卖点" in block2 and "九大 FAQ" in block2,
        "decision 4 兜底：handbook_id=None 时自动套用唯一 ready Handbook",
    )

    # ---- B) API 端点：创建会话带 handbook_id ----
    logger.info("=== B) POST /api/sessions 带 handbook_id ===")
    with TestClient(app) as client:
        # 取一个 persona
        r = client.get("/api/personas?limit=1")
        _check(r.status_code == 200, f"GET personas: {r.status_code}")
        persona_list = r.json().get("items", [])
        _check(len(persona_list) >= 1, "至少 1 个 persona")
        persona_id = persona_list[0]["id"]

        # 创建会话（带 handbook_id）
        r = client.post("/api/sessions", json={
            "persona_id": int(persona_id),
            "topic": "smoke v2 handbook test",
            "handbook_id": int(hb_id),
            "max_rounds": 8,
        })
        _check(r.status_code == 201, f"POST /api/sessions: {r.status_code} body={r.text[:200]}")
        body = r.json()
        _check(body.get("handbook_id") == int(hb_id),
               f"返回体 handbook_id={body.get('handbook_id')} 应 ={hb_id}")
        sess_id = body["id"]
        logger.info("  created session=%s handbook_id=%s", sess_id, body.get("handbook_id"))

        # GET 详情确认
        r = client.get(f"/api/sessions/{sess_id}")
        _check(r.status_code == 200, "GET session detail")
        _check(r.json().get("handbook_id") == int(hb_id),
               "详情 handbook_id 透出正确")

        # session_id = session_{timestamp}_{persona_id} 精度到秒，必须 sleep 避免撞库
        time.sleep(1.1)

        # 创建会话不传 handbook_id（验证返回体）
        r = client.post("/api/sessions", json={
            "persona_id": int(persona_id),
            "topic": "smoke v2 no handbook id",
            "max_rounds": 8,
        })
        _check(r.status_code == 201, f"POST session 无 handbook_id 也接受: {r.text[:200]}")
        _check(r.json().get("handbook_id") is None,
               f"未传 handbook_id 时返回应为 null，实际 {r.json().get('handbook_id')}")

        time.sleep(1.1)

        # 不存在 handbook_id 应 404
        r = client.post("/api/sessions", json={
            "persona_id": int(persona_id),
            "topic": "bad handbook",
            "handbook_id": 9999999,
            "max_rounds": 8,
        })
        _check(r.status_code == 404, f"非法 handbook_id 应 404，实际 {r.status_code}")

        # 清理（删掉刚才两条 throwaway session）
        # 注：找不到删除接口就略过

    # ---- C) sales_prompt.md 模板含 {handbook_block} ----
    logger.info("=== C) prompts/sales_prompt.md 占位检查 ===")
    tpl = (ROOT / "prompts" / "sales_prompt.md").read_text(encoding="utf-8")
    _check("{handbook_block}" in tpl, "sales_prompt.md 含 {handbook_block} 占位符")

    logger.info("=== Handbook v2 烟雾测试通过 ===")


if __name__ == "__main__":
    main()
