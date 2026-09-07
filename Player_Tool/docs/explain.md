# PVZ_Player_Tool 结构说明

PVZ_Player_Tool 负责 `pp.dat -> pp.bin -> pp.json`、反向重建，以及 `pp.json` 中植物相关数据的读取与修改。

## 第一层

- `main.py`：唯一直接执行入口，只负责把运行交给 `app/cli.py`。
- `params.json`：本工具唯一配置文件，保存 Android 访问、输出文件名与 RTON 加密参数。

## app

- `cli.py`：命令行参数与一次性交互菜单。一次任务完成后直接退出。

## services

- `export.py`：编排 `pp.dat -> pp.bin -> pp.json`，生成 JSON 后调用核心数据检查。
- `import_pp.py`：编排 `pp.json -> changed.bin -> changed.dat -> 游戏文件`。
- `inspect.py`：读取 `pp.json` 核心植物数据，通过 `table/` 把 JSON ID 转为英文名和中文名。
- `inventory.py`：植物、碎片、等级的统一增删改查入口，并负责 PPRS/PSLS 校验和写回验证。
- `diff.py`：比较两个 `pp.json`，植物差异自动补充英文名和中文名。

## domain

- `catalog.py`：读取 `table/plants.json` 与 `table/json_fields.json`。
- `profile.py`：定位 PlayerInfo、校验 `p/psla/ppr` 并生成植物状态对象。
- `signatures.py`：计算与验证 `pprs/psls`；`ppr/psla` 的原顺序属于签名输入，禁止排序。
- `inventory.py`：纯植物数据操作，不负责文件 IO 或命令行。
- `models.py`：各工作流使用的 dataclass 请求和路径对象。
- `errors.py`：PVZ_Player_Tool 统一业务异常。

## formats

- `pp_dat.py`：pp.dat 加密容器验证与加解密包装。
- `rton_reader.py`：将 pp.bin 的 RTON 解析为 Python/JSON 数据。
- `typed_rton.py`：读取原始 RTON 类型模板，并按模板从修改后的 JSON 重建 RTON。

## infrastructure

- `android.py`：Shizuku/rish、run-as 和应用私有文件读写。
- `files.py`：SHA-256、原子写入、JSON 文件读写。
- `project_context.py`：统一定位项目根目录、`PVZ_Json/`、`pcpid.txt`，并负责 PCPID 自动发现。任何业务脚本都不自己拼 `../`。
- `services/pcpid.py`：查看/强制刷新 PCPID；刷新后统一覆盖项目根目录 `pcpid.txt`。

## core

- `rijndael_cipher.py`：Rijndael CBC 底层实现。
- `rton_encryption.py`：PVZ RTON 加解密规则。
- `conversion_settings.py`：向底层加密模块提供根 `params.json` 中的 RTON 参数。

## table

- `plants.json`：植物表大全。CRUD 输入仍使用 `json_id`，输出自动追加英文名和中文名。
- `json_fields.json`：本工具实际使用的 PlayerInfo 字段对照表。

## 植物数据规则

- `p`：已拥有植物 JSON ID。
- `psla`：植物等级；`icpi` 是植物 JSON ID，`icl` 是等级。
- `ppr`：植物碎片；`pi` 是植物 JSON ID，`pc` 是碎片数量。
- `psls`：植物等级完整性摘要。
- `pprs`：植物碎片完整性摘要。
- “修除植物违法”只删除 `psla` 中“存在等级但植物不在 `p` 中”的记录，并同步重算 `psls`。


## 固定项目路径规则

标准结构：

```text
/storage/emulated/0/aPVZ/
├── pcpid.txt
├── PVZ_Json/
│   ├── pp.dat
│   ├── pp.bin
│   └── pp.json
└── PVZ_Tools/
    └── PVZ_Player_Tool/
        └── main.py
```

`PVZ_Player_Tool` 只需要知道自身目录；项目根按 `PVZ_Player_Tool -> PVZ_Tools -> aPVZ` 计算。
因此 `pcpid.txt` 的实际路径为 `/storage/emulated/0/aPVZ/pcpid.txt`，业务模块不写 `../../pcpid.txt` 或 `../../../pcpid.txt`。

交互菜单 `9. 获取/刷新 PCPID` 会从游戏私有目录自动获取并覆盖该文件。植物碎片/等级操作若发现保存的 PCPID 无法验证 `pprs/psls`，会自动刷新一次再验证；如果用户显式传入 `--pcpid`，则以显式值为准，不擅自覆盖。
