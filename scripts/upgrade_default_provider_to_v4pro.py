"""把 DB 中所有 base_url 指向 DeepSeek 的 provider 模型名升级到 deepseek-v4-pro。

背景：LLM 客户端的优先级是 DB default provider > .env，
所以只改 .env 不一定生效。本脚本一次性把 DeepSeek 类 provider
的 model_name 从老别名（deepseek-chat / deepseek-reasoner / deepseekV4-pro 等）
升级到 deepseek-v4-pro，并把 temperature 调到 1.0（DeepSeek 推荐的对话温度）。
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

from src.storage import db as sdb  # noqa: E402


TARGET_MODEL = "deepseek-v4-pro"
LEGACY_MODELS = {
    "deepseek-chat",
    "deepseek-reasoner",
    "deepseekv4-pro",  # 旧拼写
    "deepseekv4_pro",
    "",
}


def _is_deepseek(base_url: str) -> bool:
    return "deepseek.com" in (base_url or "").lower()


def main() -> None:
    with sdb.connection_scope() as conn:
        rows = conn.execute(
            "SELECT id, name, base_url, model_name, temperature, is_default "
            "FROM llm_providers ORDER BY id"
        ).fetchall()
        if not rows:
            print("llm_providers 表为空，无需升级。")
            return

        updated = 0
        for row in rows:
            r = dict(row)
            if not _is_deepseek(r.get("base_url", "")):
                print(
                    f"[skip] id={r['id']} name={r['name']} "
                    f"base_url={r['base_url']} 非 DeepSeek，不动。"
                )
                continue

            current_model = (r.get("model_name") or "").strip().lower()
            need_model = current_model in LEGACY_MODELS or current_model != TARGET_MODEL.lower()
            need_temp = float(r.get("temperature") or 0) < 0.95  # 升到 1.0

            if not need_model and not need_temp:
                print(
                    f"[ok]   id={r['id']} name={r['name']} "
                    f"已是 {r['model_name']} temp={r['temperature']}"
                )
                continue

            sets = []
            params: list = []
            if need_model:
                sets.append("model_name = ?")
                params.append(TARGET_MODEL)
            if need_temp:
                sets.append("temperature = ?")
                params.append(1.0)
            params.append(r["id"])
            sql = f"UPDATE llm_providers SET {', '.join(sets)} WHERE id = ?"
            conn.execute(sql, params)
            updated += 1
            print(
                f"[upgr] id={r['id']} name={r['name']} "
                f"{r['model_name']} -> {TARGET_MODEL if need_model else r['model_name']}; "
                f"temp {r['temperature']} -> {1.0 if need_temp else r['temperature']}"
            )

        if updated:
            conn.commit()
            print(f"\n升级完成，共更新 {updated} 个 provider。")
        else:
            print("\n所有 DeepSeek provider 已是最新配置。")


if __name__ == "__main__":
    main()
