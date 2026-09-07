# PvZ2 Resource Tool

一个用于《Plants vs. Zombies 2》资源文件拆包、转换、回包与工程反向回包的 Python 工具。

项目主要用于研究以下资源转换链：

```text
SMF / RSLB ↔ RSB ↔ RSG ↔ encrypted RTON ↔ RTON ↔ JSON
```

## 环境

- Python 3.13
- 主要在 Android / Termux 环境开发和测试
- 当前代码仅使用 Python 标准库，无需安装第三方 Python 依赖

## 版本说明

本项目主要基于 PvZ2 **4.1.9 / 4.2.3** 的资源进行研究和测试。

不同游戏版本之间可能存在资源结构、MD5、数据布局或其他版本相关差异，因此不能保证所有文件在其他版本中都能直接处理。格式解析、转换和回包的主要算法逻辑仍可作为参考。

## 使用

直接运行：

```bash
python main.py
```

不带参数时进入交互模式。

查看命令行帮助：

```bash
python main.py --help
```

示例：

```bash
python main.py -unpack dynamic.rsb.smf -json -j 4
python main.py -pack /path/to/04_JSON -rsb -j 4
python main.py -pack /path/to/04_JSON -smf -j 4
python main.py -reverse /path/to/project
```

`-j` 用于指定并发数；Android 手机上通常建议使用 2~4。

## 目录结构

```text
app/            CLI 与交互入口
binary_codecs/  SMF / RSLB 二进制编解码
config/         配置加载与校验
converters/     RSB / RSG / RTON / JSON 转换
core/           底层格式、加密与编解码算法
domain/         格式定义与异常
infrastructure/ 文件、路径、哈希与并发辅助
project/        工程目录、index.md 与反向回包
services/       打包 / 解包流程编排
docs/           补充说明
main.py         唯一直接执行入口
params.json     工具配置
```

## 当前限制

- 部分格式或特殊资源可能仍存在未覆盖的边界情况。
- PAM 等未实现的资源转换逻辑不在当前工具支持范围内。
- 版本相关的资源结构或参数可能需要针对具体游戏版本重新验证。
- 建议在回包前后使用工具提供的验证功能检查结果。

## 项目原则

`main.py` 是唯一直接执行入口。业务流程、格式转换和底层二进制算法分别放在独立模块中，避免把所有逻辑集中在单一脚本。

本仓库提供的是研究和资源处理工具，不包含游戏本体或商业资源文件。
