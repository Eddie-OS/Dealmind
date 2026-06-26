"""Sprint 1 烟雾测试：Handbook CRUD + 文件上传 + 解析 全链路在进程内跑一遍。

只测：
1. GET  /api/handbooks 能拿到 seed 进去的那条
2. POST /api/handbooks 新建一个 throw-away handbook
3. POST /api/handbooks/{id}/files 上传 PPTX，确认解析成 parsed_text
4. GET  /api/handbooks/{id} 能看到 structure_stats
5. DELETE /api/handbooks/{id} 删干净

不真正调 LLM，因此 extract 接口预期返回 501（占位）。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

from fastapi.testclient import TestClient

from src.api.server import app


logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("smoke")

PPTX = ROOT / "训练文件" / "5. Laurent_HUAWEI MatePad 12 X_Instore Training Guide.pptx"


def _check(cond: bool, msg: str) -> None:
    if cond:
        logger.info("OK   %s", msg)
    else:
        logger.error("FAIL %s", msg)
        sys.exit(2)


def main() -> None:
    if not PPTX.exists():
        logger.error("PPTX 不存在: %s", PPTX)
        sys.exit(1)

    with TestClient(app) as client:
        # 1) 列表必须包含 seed 进去的那条
        r = client.get("/api/handbooks")
        _check(r.status_code == 200, f"GET /api/handbooks → {r.status_code}")
        items = r.json().get("items", [])
        _check(len(items) >= 1, f"列表至少有 1 条，实际 {len(items)}")
        seeded = items[0]
        logger.info("  seeded handbook id=%s name=%s status=%s",
                    seeded["id"], seeded["name"], seeded["status"])

        # 2) seed 那条 GET 详情
        r = client.get(f"/api/handbooks/{seeded['id']}")
        _check(r.status_code == 200, f"GET /api/handbooks/{seeded['id']}")
        detail = r.json()
        stats = detail.get("structure_stats", {})
        _check(stats.get("selling_points") == 3, f"selling_points = {stats.get('selling_points')}")
        _check(stats.get("faq") == 9, f"faq = {stats.get('faq')}")
        _check(stats.get("demo_actions") == 10, f"demo_actions = {stats.get('demo_actions')}")

        # 3) 新建一个 throw-away handbook
        r = client.post("/api/handbooks", json={
            "name": "__smoke_test_handbook__",
            "description": "smoke test (auto delete)",
        })
        _check(r.status_code == 201, f"POST /api/handbooks → {r.status_code}: {r.text[:200]}")
        new = r.json()
        new_id = new["id"]
        _check(new["status"] == "draft", f"新建状态应 draft，实际 {new['status']}")

        # 4) 上传文件
        with PPTX.open("rb") as f:
            r = client.post(
                f"/api/handbooks/{new_id}/files",
                files={"files": (PPTX.name, f,
                       "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
            )
        _check(r.status_code == 201, f"POST /api/handbooks/{new_id}/files → {r.status_code}: {r.text[:200]}")
        up = r.json()
        _check(up["imported"] == 1, f"imported=1，实际 {up['imported']}")
        f0 = up["items"][0]
        _check(f0["status"] == "parsed", f"解析状态 parsed，实际 {f0['status']}: err={f0.get('error_msg')}")
        _check(f0["parsed_text_length"] > 100, f"parsed_text_length={f0['parsed_text_length']}")
        logger.info("  uploaded file id=%s parsed_text_len=%d",
                    f0["id"], f0["parsed_text_length"])

        # 5) 文件列表 + 详情（含全文）
        r = client.get(f"/api/handbooks/{new_id}/files")
        _check(r.status_code == 200, "GET files list")
        _check(r.json()["total"] == 1, "文件列表 1 条")

        r = client.get(f"/api/handbooks/{new_id}/files/{f0['id']}?include_text=true")
        _check(r.status_code == 200, "GET file detail with text")
        text = r.json().get("parsed_text") or ""
        _check(len(text) > 100, f"parsed_text 长度 {len(text)}")
        snippet = (text or "").strip().split("\n")[0][:60].encode("ascii", "replace").decode()
        logger.info("  parsed_text head: %s", snippet)

        # 6) extract 接口当前为 501 占位
        r = client.post(f"/api/handbooks/{new_id}/extract")
        _check(
            r.status_code == 501,
            f"POST /extract 占位 501，实际 {r.status_code}",
        )

        # 7) 清理
        r = client.delete(f"/api/handbooks/{new_id}")
        _check(r.status_code == 204, f"DELETE /api/handbooks/{new_id} → {r.status_code}")

        r = client.get(f"/api/handbooks/{new_id}")
        _check(r.status_code == 404, f"删除后 GET 应 404，实际 {r.status_code}")

    logger.info("=== Sprint 1 烟雾测试通过 ===")


if __name__ == "__main__":
    main()
