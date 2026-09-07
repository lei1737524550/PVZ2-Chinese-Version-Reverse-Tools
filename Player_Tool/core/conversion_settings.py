"""向底层加密模块暴露 RTON 转换参数。"""

from __future__ import annotations

from config.settings import SETTINGS

RTON_ENCRYPTION_SEED = SETTINGS.rton.encryption_seed
RTON_BLOCK_SIZE = SETTINGS.rton.block_size
