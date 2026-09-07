"""向底层转换算法暴露稳定的只读配置常量。"""

from config import SETTINGS

_CONFIG = SETTINGS.conversion

RTON_ENCRYPTION_SEED = _CONFIG.rton_encryption_seed
RTON_BLOCK_SIZE = _CONFIG.rton_block_size
RSG_NAME_PREFIXES = _CONFIG.rsg_name_prefixes
RSG_NAME_SUFFIXES = _CONFIG.rsg_name_suffixes
INTERNAL_PATH_PREFIXES = _CONFIG.internal_path_prefixes
INTERNAL_PATH_SUFFIXES = _CONFIG.internal_path_suffixes
JSON_INDENT = _CONFIG.json_indent
JSON_ENSURE_ASCII = _CONFIG.json_ensure_ascii
JSON_SORT_KEYS = _CONFIG.json_sort_keys
JSON_SORT_VALUES = _CONFIG.json_sort_values
JSON_REPAIR_FILES = _CONFIG.json_repair_files
