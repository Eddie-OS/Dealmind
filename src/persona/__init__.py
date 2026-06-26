"""Persona 业务模块：解析、抽参、生成、预填。

对外主入口：
- parse_persona_file: 多格式人设文件解析
- extract_pressure_profile: prompt -> 9 维量化参数
- seed_built_in_personas: 启动时预填 44 个 panel persona
"""

from src.persona.parser import (
    PersonaParseError,
    parse_persona_file,
    parse_persona_payload,
)
from src.persona.pressure_extractor import (
    DEFAULT_PRESSURE,
    extract_pressure_profile,
)
from src.persona.seed import seed_built_in_personas

__all__ = [
    "PersonaParseError",
    "parse_persona_file",
    "parse_persona_payload",
    "extract_pressure_profile",
    "DEFAULT_PRESSURE",
    "seed_built_in_personas",
]
