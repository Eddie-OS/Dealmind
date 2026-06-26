"""验证 5 个 stage 的 _stage_pack 输出（避免 PowerShell 转义陷阱）。"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 强制 UTF-8 输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from src.agents import _stage_pack
from src.schema import DialogueState, PersonaProfile, PressureProfile


def main() -> int:
    persona = PersonaProfile(
        id="p1",
        name="Test",
        pressure_profile=PressureProfile(
            price_sensitivity=0.5, trust_threshold=0.5, patience=0.5,
            competitor_awareness=0.5, decision_power=0.5,
            emotion_volatility=0.5, need_urgency=0.5, skepticism=0.5,
            bargaining_aggressiveness=0.5,
        ),
    )
    for sid in ["S1", "S2", "S3", "S4", "S5"]:
        ds = DialogueState(
            session_id="s1", topic="手机销售", product_text="",
            persona_profile=persona,
        )
        ds.current_stage_id = sid
        pack = _stage_pack(ds)
        print(f"=== {sid} · {pack['current_stage_cn']} ===")
        print(f"allowed playbook: {pack['allowed_playbook_actions_csv']}")
        print(pack["stage_playbook_block"][:400])
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
