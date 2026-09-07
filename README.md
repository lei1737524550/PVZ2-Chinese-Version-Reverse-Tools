# PVZ2 Tools

一个面向《Plants vs. Zombies 2》Android 资源研究与玩家数据处理的 Python 工具集。

## 环境与兼容性

- Python 3.13
- 主要在 Android / Termux 环境开发和测试
- 主要测试游戏版本：PvZ2 4.1.9 / 4.2.3
- 部分 Android 文件访问功能会用到 Shizuku、rish、A Shell / Termux 等环境

不同游戏版本之间可能存在资源结构、数据地址、MD5 或硬编码参数差异。因此部分版本相关数据可能失效，但格式解析、转换及主要算法逻辑仍可作为参考。

## 项目组成

### Resource_Tool

游戏资源拆包、转换和回包工具，主要处理：

```text
SMF / RSLB ↔ RSB ↔ RSG ↔ encrypted RTON ↔ RTON ↔ JSON
```

运行：

```bash
cd Resource_Tool
python main.py
```

查看参数：

```bash
python main.py --help
```

### Player_Tool

玩家数据工具，围绕 `pp.dat / pp.json` 提供转换、查看及数据管理功能，包括植物、等级、碎片、PCPID 与相关数据验证。

默认 JSON 工作位置使用：

```text
PVZ_Json/pp.json
```

运行：

```bash
cd Player_Tool
python main.py
```

查看参数：

```bash
python main.py --help
```

## 当前限制

- PAM 等部分资源转换逻辑尚未实现。
- 版本相关的地址、MD5、数据结构和参数需要针对具体游戏版本重新验证。
- Android 集成功能取决于设备权限和 Shizuku/rish 等本地环境。
- 本项目不包含游戏本体或商业资源文件。

## 目录

```text
PVZ2-Tools/
├── README.md
├── .gitignore
├── Resource_Tool/
│   ├── main.py
│   └── ...
└── Player_Tool/
    ├── main.py
    └── ...
```
