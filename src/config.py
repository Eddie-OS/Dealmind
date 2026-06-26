"""全局配置加载。从 .env 读取，统一供 LLM 层与 runner 使用。"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from rich.logging import RichHandler


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "logs"


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    model_name: str
    temperature: float
    max_retries: int

    def redacted(self) -> dict:
        """返回不含敏感信息的字典，用于日志。"""
        return {
            "base_url": self.base_url,
            "model_name": self.model_name,
            "temperature": self.temperature,
            "max_retries": self.max_retries,
            "api_key_set": bool(self.api_key),
        }


def _read_env(name: str, default: Optional[str] = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(
            f"环境变量 {name} 未设置。请检查项目根目录下的 .env 文件，"
            f"参考 .env.example 进行配置。"
        )
    return value or ""


def load_settings(dotenv_path: Optional[Path] = None) -> Settings:
    """读取 .env 并构造 Settings。

    优先级：显式传入的 dotenv_path > 项目根目录 .env > 进程已存在的环境变量。
    """
    env_path = dotenv_path or (PROJECT_ROOT / ".env")
    if env_path.exists():
        load_dotenv(env_path, override=False)

    try:
        temperature = float(_read_env("TEMPERATURE", "1.0"))
    except ValueError as exc:
        raise RuntimeError(f"TEMPERATURE 必须是数字，当前值无法解析: {exc}") from exc

    try:
        max_retries = int(_read_env("MAX_RETRIES", "2"))
    except ValueError as exc:
        raise RuntimeError(f"MAX_RETRIES 必须是整数，当前值无法解析: {exc}") from exc

    return Settings(
        api_key=_read_env("OPENAI_API_KEY", required=True),
        base_url=_read_env("OPENAI_BASE_URL", "https://api.deepseek.com"),
        model_name=_read_env("MODEL_NAME", "deepseek-v4-pro"),
        temperature=temperature,
        max_retries=max_retries,
    )


_LOGGING_INITIALIZED = False


def setup_logging(
    log_dir: Optional[Path] = None,
    level: int = logging.INFO,
    backup_count: int = 30,
) -> Path:
    """初始化全局日志：rotating file handler（按天滚动）+ rich 控制台并存。

    幂等：重复调用不会叠加 handler。

    Args:
        log_dir: 日志目录，默认 logs/。
        level: 根 logger 等级。
        backup_count: 保留的历史日志文件数（按天 = 30 天）。

    Returns:
        当日日志文件路径，方便上层打印 / 自检。
    """
    global _LOGGING_INITIALIZED

    target_dir = log_dir or LOG_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    log_file = target_dir / "app.log"

    root = logging.getLogger()
    root.setLevel(level)

    if _LOGGING_INITIALIZED:
        return target_dir / f"app.log.{datetime.now().strftime('%Y-%m-%d')}"

    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=backup_count,
        encoding="utf-8",
        utc=False,
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setLevel(level)
    file_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(file_handler)

    rich_handler = RichHandler(
        rich_tracebacks=True,
        show_time=True,
        show_path=False,
        markup=True,
    )
    rich_handler.setLevel(level)
    rich_handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(rich_handler)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    _LOGGING_INITIALIZED = True
    logging.getLogger(__name__).info(
        "logging initialized: file=%s level=%s backup=%dd",
        log_file, logging.getLevelName(level), backup_count,
    )
    return log_file
