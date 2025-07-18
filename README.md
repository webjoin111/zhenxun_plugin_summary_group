# 群聊总结插件 (summary_group)

[![zhenxun_bot](https://img.shields.io/badge/zhenxun_bot-v0.1.6.5+-orange)](https://github.com/HibiKier/zhenxun_bot)
[![python](https://img.shields.io/badge/python-3.8+-blue)](https://www.python.org/)
[![nonebot2](https://img.shields.io/badge/nonebot2-2.0.0+-red)](https://github.com/nonebot/nonebot2)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

基于 AI 的群聊消息智能总结插件，支持实时总结和定时总结功能。本插件是 [nonebot_plugin_summary_group](https://github.com/StillMisty/nonebot_plugin_summary_group) 的 Zhenxun Bot 适配版本，提供了强大的群聊内容分析和总结能力。

## ⚙️ 核心配置

### 1. AI 模型配置 (必需)

⚠️ **重要**：本插件的运行依赖于 Zhenxun Bot 的核心 LLM 服务。您必须首先在机器人的主配置文件 (`data/configs/config.yaml`) 中正确配置 `AI.PROVIDERS`，并填入您可用的 AI 模型 API Key。

一个最小化的 `AI.PROVIDERS` 配置示例：
```yaml
AI:
  PROVIDERS:
    # 示例：使用 Gemini
    - name: Gemini
      api_key: "AIzaSy..."
      api_type: gemini
      models:
        - model_name: gemini-2.5-flash
    # 示例：使用 DeepSeek
    - name: DeepSeek
      api_key: "sk-..."
      api_base: https://api.deepseek.com
      api_type: openai
      models:
        - model_name: deepseek-chat
```

### 2. 插件专属配置

本插件的配置项位于 `data/configs/config.yaml` 文件的 `summary_group` 模块下。首次加载时会自动生成默认配置。

| 配置项                      | 类型   | 默认值                    | 说明                                                                                    |
| --------------------------- | ------ | ------------------------- | --------------------------------------------------------------------------------------- |
| `SUMMARY_MODEL_NAME`        | `str`  | `Gemini/gemini-2.5-flash` | 本插件**全局默认**使用的 AI 模型，格式为 `ProviderName/ModelName`。会被分群配置覆盖。   |
| `SUMMARY_DEFAULT_STYLE`     | `str`  | `null`                    | 本插件**全局默认**的总结风格。会被分群配置覆盖。                                        |
| `SUMMARY_MAX_LENGTH`        | `int`  | `1000`                    | 手动触发总结时，可获取的最大消息数量。                                                  |
| `SUMMARY_MIN_LENGTH`        | `int`  | `50`                      | 触发总结所需的最少有效消息数量。                                                        |
| `SUMMARY_COOL_DOWN`         | `int`  | `60`                      | 用户手动触发总结的冷却时间（秒）。                                                      |
| `summary_output_type`       | `str`  | `image`                   | 总结报告的输出格式，可选值为 `image` 或 `text`。                                        |
| `summary_fallback_enabled`  | `bool` | `false`                   | 当图片生成失败时，是否自动降级为纯文本输出。                                            |
| `summary_theme`             | `str`  | `dark`                    | 总结图片的主题样式，可选值为 `dark`, `light`, `cyber`。                                 |
| `ENABLE_AVATAR_ENHANCEMENT` | `bool` | `true`                    | 是否在图片报告中为用户名嵌入头像。**开启此项会增加图片生成时间和资源消耗。**            |
| `USE_DB_HISTORY`            | `bool` | `false`                   | 是否优先从数据库 (`chat_history` 表) 获取聊天记录。可以提升速度，但可能丢失非文本信息。 |
| `EXCLUDE_BOT_MESSAGES`      | `bool` | `false`                   | 是否在总结时排除 Bot 自身发送的消息。                                                   |
| `MESSAGE_CACHE_TTL_SECONDS` | `int`  | `300`                     | 从 API 获取的消息列表的缓存时间（秒），`0` 表示禁用。                                   |

## 📖 命令使用

### 核心功能 (所有用户)

*   **生成总结**
    *   **命令**: `总结 <数量>`
    *   **说明**: 对群内最近指定数量的消息进行总结。
    *   **示例**: `总结 200`

*   **总结特定用户**
    *   **命令**: `总结 <数量> @用户1 @用户2 ...`
    *   **说明**: 仅总结被 @ 的一个或多个用户的发言。
    *   **示例**: `总结 300 @张三 @李四`

*   **总结特定内容**
    *   **命令**: `总结 <数量> <关键词>`
    *   **说明**: 仅总结包含指定关键词的消息。
    *   **示例**: `总结 500 原神`

*   **指定风格**
    *   **命令**: `总结 <数量> -p <风格>`
    *   **说明**: 使用指定的风格（Prompt）来生成本次总结。
    *   **示例**: `总结 100 -p 以阴阳怪气的风格锐评`

> 💡 **提示**: 超级用户可以在以上所有命令后追加 `-g <群号>` 来对任意群聊进行操作。

### 🛠️ 管理员用法

*   **设置定时总结**
    *   **命令**: `定时总结 <时间> [数量] [-p <风格>]`
    *   **说明**: 为本群设置一个每日定时的总结任务。
    *   **时间格式**: `HH:MM` (如 `23:30`) 或 `HHMM` (如 `2330`)。
    *   **示例**: `定时总结 23:59 800 -p 正式汇报`

*   **取消定时总结**
    *   **命令**: `定时总结取消`
    *   **说明**: 取消本群的定时总结任务。

*   **配置本群默认风格**
    *   **命令**: `总结配置 风格 设置 <风格名称>`
    *   **说明**: 为本群设置一个默认的总结风格，无需每次手动指定。
    *   **示例**: `总结配置 风格 设置 雌小鬼`

*   **移除本群默认风格**
    *   **命令**: `总结配置 风格 移除`
    *   **说明**: 移除为本群设置的默认风格，使其恢复使用插件的全局默认风格。

*   **查看本群配置**
    *   **命令**: `总结配置`
    *   **说明**: 查看当前群聊生效的模型和风格配置。

> 💡 **提示**: 超级用户可以在以上命令后追加 `-g <群号>` 或 `-all` (仅限定时总结) 来管理任意群聊。

### 👑 超级用户用法

*   **管理插件全局默认模型**
    *   `总结模型 列表`: 查看所有可用的 AI 模型。
    *   `总结模型 设置 <Provider/Model>`: 设置本插件使用的全局默认模型。

*   **管理插件全局默认风格**
    *   `总结风格 设置 <风格名称>`: 设置本插件使用的全局默认总结风格。
    *   `总结风格 移除`: 移除全局默认风格。

*   **管理任意群组的特定模型**
    *   `总结配置 模型 设置 <模型名称> -g <群号>`: 为指定群聊设置一个特定的默认模型。
    *   `总结配置 模型 移除 -g <群号>`: 移除指定群聊的特定模型设置。

## 🔮 配置优先级说明

本插件的模型和风格选择遵循以下覆盖逻辑，优先级从高到低：

1.  **命令临时指定**: 在 `总结` 命令中使用 `-p` 参数指定的风格。
2.  **群组特定配置**: 使用 `总结配置` 命令为**单个群聊**设置的模型和风格。
3.  **插件全局配置**: 使用 `总结模型` 和 `总结风格` 命令为**整个插件**设置的默认模型和风格。
4.  **LLM 核心服务默认**: 如果以上均未配置，则使用 Zhenxun Bot 核心 LLM 服务的全局默认模型。

## 📋 更新日志

### [3.0.0] - 重大架构升级


**🚨 破坏性变更**
- 配置结构完全重构，旧版配置不兼容
- 移除独立AI模型管理和系统维护命令
- 命令语法更新，请参阅新版文档

**🏗️ 核心重构**
- 深度集成Zhenxun Bot核心服务（AI模型、定时任务、API管理）
- 统一使用 `scheduler_manager` 和 `AI.PROVIDERS`
- 集成密钥轮询和负载均衡机制

**✨ 新增功能**
- 🎨 三种图片主题：`dark` / `light` / `cyber`
- 👤 用户头像嵌入和高亮显示
- ⚡ 智能缓存机制，显著提升响应速度
- ✂️ 用户名智能截断，优化显示效果

## [2.2.0]
- ✨ 新增用户头像显示功能（默认关闭，需配置启用）
- ♻️ 配置管理重构，迁移至独立 `config.py` 文件
- ♻️ 工具模块重构，优化代码结构和可维护性
- ⚡️ 性能优化，改进用户信息获取和消息处理
- 🐛 修复定时任务和异步处理相关问题

## [2.1.0]
- 🎨 新增主题配置支持
- ✨ 智能API密钥轮换策略
- 🚀 消息处理逻辑优化，支持并发获取用户信息
- 🔍 新增从数据库读取聊天记录的配置选项
- 🔄 模型配置迁移到AI模块

## [2.0.0]
- 🤖 多AI模型支持，支持模型切换和管理
- 🔧 分群模型和风格配置功能
- ♻️ 重构模型配置结构，使用 `AI.PROVIDERS` 管理
- 👑 模型相关设置权限提升至超级用户级别
- 🐛 修复多项功能和配置相关问题

## [1.0.0]
- 📝 基础群聊总结功能（指定数量、用户、关键词、风格）
- ⏰ 定时总结功能
- 🖼️ 图片和文本双输出模式
- 🛡️ 权限控制和冷却时间限制

## 致谢

特别感谢：

- [nonebot_plugin_summary_group](https://github.com/StillMisty/nonebot_plugin_summary_group) - 本项目的原始版本，由 [@StillMisty](https://github.com/StillMisty) 开发
- [Zhenxun Bot](https://github.com/HibiKier/zhenxun_bot) - 强大的机器人框架
- [NoneBot2](https://github.com/nonebot/nonebot2) - 优秀的机器人框架
- 所有贡献者和用户

## 许可证

本项目采用 MIT 许可证。详见 LICENSE 文件。

原项目 [nonebot_plugin_summary_group](https://github.com/StillMisty/nonebot_plugin_summary_group) 采用 Apache-2.0 许可证。
