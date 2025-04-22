# 群聊总结插件 (summary_group)

[![zhenxun_bot](https://img.shields.io/badge/zhenxun_bot-v0.1.6.5+-orange)](https://github.com/HibiKier/zhenxun_bot)
[![python](https://img.shields.io/badge/python-3.8+-blue)](https://www.python.org/)
[![nonebot2](https://img.shields.io/badge/nonebot2-2.0.0+-red)](https://github.com/nonebot/nonebot2)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

基于 AI 的群聊消息智能总结插件，支持实时总结和定时总结功能。本插件是 [nonebot_plugin_summary_group](https://github.com/StillMisty/nonebot_plugin_summary_group) 的 Zhenxun Bot 适配版本，提供了强大的群聊内容分析和总结能力。

## 目录

- [群聊总结插件 (summary\_group)](#群聊总结插件-summary_group)
  - [目录](#目录)
  - [关于本项目](#关于本项目)
  - [功能特性](#功能特性)
  - [安装方法](#安装方法)
  - [基础命令](#基础命令)
    - [普通用户命令](#普通用户命令)
    - [超级用户命令](#超级用户命令)
  - [配置说明](#配置说明)
    - [模型配置](#模型配置)
      - [配置示例](#配置示例)
    - [配置说明](#配置说明-1)
      - [Provider 配置](#provider-配置)
      - [Model 配置](#model-配置)
    - [模型切换与管理](#模型切换与管理)
      - [全局模型切换](#全局模型切换)
      - [群组特定模型设置](#群组特定模型设置)
      - [移除群组特定模型](#移除群组特定模型)
      - [查看可用模型](#查看可用模型)
      - [查看群组配置](#查看群组配置)
    - [支持的 API 类型](#支持的-api-类型)
    - [如何获取各大模型的 API 密钥](#如何获取各大模型的-api-密钥)
      - [DeepSeek](#deepseek)
      - [GLM (智谱 AI)](#glm-智谱-ai)
      - [Gemini](#gemini)
      - [ARK (火山方舟)](#ark-火山方舟)
      - [OpenAI 兼容服务](#openai-兼容服务)
  - [功能演示](#功能演示)
    - [基础总结功能](#基础总结功能)
    - [定向总结功能](#定向总结功能)
    - [定时总结功能](#定时总结功能)
    - [自定义风格总结](#自定义风格总结)
  - [使用建议与最佳实践](#使用建议与最佳实践)
    - [总结效果优化](#总结效果优化)
    - [定时总结优化](#定时总结优化)
    - [系统维护](#系统维护)
    - [模型管理](#模型管理)
    - [风格设置与管理](#风格设置与管理)
      - [全局风格设置](#全局风格设置)
      - [群组风格设置](#群组风格设置)
      - [移除群组风格设置](#移除群组风格设置)
  - [常见问题](#常见问题)
    - [1. API 调用失败](#1-api-调用失败)
    - [2. 定时任务未执行](#2-定时任务未执行)
    - [3. 总结质量问题](#3-总结质量问题)
    - [4. 模型配置问题](#4-模型配置问题)
  - [技术支持](#技术支持)
  - [致谢](#致谢)
  - [许可证](#许可证)

## 关于本项目

本项目是基于 [@StillMisty](https://github.com/StillMisty) 开发的 [nonebot_plugin_summary_group](https://github.com/StillMisty/nonebot_plugin_summary_group) 插件进行改造，专门适配 Zhenxun Bot 框架。在保留原有核心功能的基础上，我们：

1. 重构了配置系统以适配 Zhenxun Bot
2. 增加了更多自定义功能（如总结风格）
3. 添加了系统健康检查等维护工具
4. 优化了任务调度和并发处理

## 功能特性

- 🤖 基于先进 AI 模型的智能总结
- ⏰ 支持定时自动总结功能
- 🎯 支持针对特定用户或关键词的定向总结
- 🎨 支持自定义总结风格（正式、锐评等）
- 📊 完整的任务调度和健康监控
- 🛠 内置系统诊断和修复工具

## 安装方法

1. 确保你已经安装了 Zhenxun Bot
2. 将本插件目录复制到 Zhenxun Bot 的 plugins 目录下
3. 在 Zhenxun Bot 的配置文件中启用插件
4. 重启 Bot 使插件生效

## 基础命令

### 普通用户命令

```
总结 [消息数量] [-p 风格] [内容] [@用户1 @用户2 ...]
```

参数说明：
- `消息数量`：要总结的消息数量
- `-p/--prompt`：可选，指定总结风格（如：正式、锐评）
- `内容`：可选，指定过滤的内容关键词
- `@用户`：可选，指定只总结特定用户的发言

示例：
- `总结 100 关于项目进度`
- `总结 500 @张三 @李四`
- `总结 200 -p 正式 关于BUG @张三`

### 超级用户命令

1. 模型管理命令：
```
总结模型列表
总结切换模型 <ProviderName/ModelName>
```

参数说明：
- `ProviderName/ModelName`：要切换到的模型，格式为“提供商名称/模型名称”

示例：
- `总结切换模型 DeepSeek/deepseek-chat`
- `总结切换模型 Gemini/gemini-2.0-flash`

2. 设置定时总结：
```
定时总结 [HH:MM或HHMM] [最少消息数量] [-p 风格] [-g 群号] [-all]
```

参数说明：
- `HH:MM或HHMM`：定时触发的时间点
- `最少消息数量`：触发总结所需的最少消息数
- `-p/--prompt`：可选，指定总结风格（如：正式、简洁、幽默）
- `-g 群号`：可选，指定特定群聊
- `-all`：可选，对所有群生效

示例：
- `定时总结 22:00 100 -g 123456`
- `定时总结 08:30 200 -p 简洁`

3. 取消定时总结：
```
定时总结取消 [-g 群号] [-all]
```

4. 查看调度状态：
```
总结调度状态 [-d]
```

5. 系统维护命令：
```
总结健康检查
总结系统修复
```

## 配置说明

### 模型配置

从 v2.0 版本开始，插件使用新的 `SUMMARY_PROVIDERS` 配置结构，支持按提供商分组管理多个 AI 模型。

插件默认已经内置了多个模型配置，包括 DeepSeek、GLM、ARK 和 Gemini，但您需要将其中的 API 密钥替换为您自己的密钥才能正常使用。

#### 配置示例

```yaml
SUMMARY_PROVIDERS: # 模型提供商配置列表
  - name: DeepSeek   # Provider 名称
    api_key: sk-******************************   # Provider 的 API Key (单个)
    api_base: https://api.deepseek.com   # Provider 的 API Base URL
    # api_type: deepseek # 可选，通常会自动推断
    # temperature: 0.5 # 可选：Provider 级别的默认温度
    # max_tokens: 8192 # 可选：Provider 级别的默认最大 tokens
    models:   # 该 Provider 下的模型列表
    - model_name: deepseek-chat     # 具体的模型名称
      max_tokens: 4096     # 可选：覆盖 Provider 的默认值
      temperature: 0.7     # 可选：覆盖 Provider 的默认值
    - model_name: deepseek-reasoner
      # 此模型将使用 Provider 级别的默认 temperature 和 max_tokens (如果设置了的话)
      # 或者使用 LLMModel 内部的默认值

  - name: GLM   # Provider 名称 (智谱 AI)
    api_key: b160c***************************   # Provider 的 API Key
    api_base: https://open.bigmodel.cn/api/paas   # Provider 的 API Base URL
    api_type: zhipu   # 建议显式指定智谱的类型
    models:
    - model_name: glm-4-flash     # 新版本模型名可能不需要日期后缀
      max_tokens: 4096
      temperature: 0.7

  - name: Gemini   # Provider 名称
    api_key:   # Provider 的 API Key (列表)
    - AIzaSyB***********************
    - AIzaSyA***********************
    - AIzaSyD***********************
    api_base: https://generativelanguage.googleapis.com   # Provider 的 API Base URL
    # api_type: gemini # 可选
    temperature: 0.8   # Provider 级别的默认温度
    # max_tokens: 8192 # Provider 级别的默认最大 tokens (Gemini 通常按输入输出分别限制，这里可设输出上限)
    models:
    - model_name: gemini-2.0-flash     # 建议使用 latest 标签
    - model_name: gemini-2.5-flash-preview-04-17     # 示例：添加另一个 Gemini 模型
      # 也将继承 Provider 的 temperature: 0.8

# 默认模型设置 (格式: ProviderName/ModelName)
SUMMARY_DEFAULT_MODEL_NAME: DeepSeek/deepseek-chat

# 其他配置项
PROXY: http://127.0.0.1:7890  # 可选：网络代理
TIME_OUT: 180  # API 请求超时时间（秒）
MAX_RETRIES: 2  # API 请求失败时的最大重试次数
RETRY_DELAY: 3  # API 请求重试前的基础延迟时间（秒）
SUMMARY_MAX_LENGTH: 800  # 手动触发总结时，默认获取的最大消息数量
SUMMARY_MIN_LENGTH: 30  # 触发总结所需的最少消息数量
SUMMARY_COOL_DOWN: 30  # 用户手动触发总结的冷却时间（秒，0表示无冷却）
SUMMARY_ADMIN_LEVEL: 10  # 设置/取消本群定时总结所需的最低管理员等级
CONCURRENT_TASKS: 3  # 同时处理总结任务的最大数量
summary_output_type: image  # 总结输出类型 (image 或 text)
summary_fallback_enabled: true  # 当图片生成失败时是否自动回退到文本模式
summary_theme: vscode_dark  # 总结图片输出的主题 (可选: light, dark, vscode_light, vscode_dark)
```

### 配置说明

#### Provider 配置

每个 Provider 配置包含以下字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | 字符串 | 是 | Provider 的唯一名称标识，用于在切换模型时指定 |
| `api_key` | 字符串或字符串列表 | 是 | Provider 的 API Key，可以是单个字符串或字符串列表（会随机选择一个使用） |
| `api_base` | 字符串 | 是 | Provider 的 API Base URL |
| `api_type` | 字符串 | 否 | API 类型，如 openai, claude, gemini, baidu 等，留空则自动推断 |
| `openai_compat` | 布尔值 | 否 | 是否对 Gemini API 使用 OpenAI 兼容模式，默认为 false |
| `temperature` | 浮点数 | 否 | Provider 级别的默认温度参数 |
| `max_tokens` | 整数 | 否 | Provider 级别的默认最大 token 限制 |
| `models` | 模型列表 | 是 | 该 Provider 支持的模型列表 |

#### Model 配置

每个 Model 配置包含以下字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `model_name` | 字符串 | 是 | 模型的具体名称，如 gemini-2.0-flash, deepseek-chat 等 |
| `temperature` | 浮点数 | 否 | 覆盖 Provider 的温度参数 |
| `max_tokens` | 整数 | 否 | 覆盖 Provider 的最大 token 限制 |

### 模型切换与管理

#### 全局模型切换

使用以下命令切换全局默认模型（需要超级用户权限）：

```
总结切换模型 ProviderName/ModelName
```

例如：
```
总结切换模型 DeepSeek/deepseek-chat
总结切换模型 Gemini/gemini-2.0-flash
```

注意：模型名称必须使用 `提供商名称/模型名称` 的格式，且必须与配置文件中的名称完全一致。

#### 群组特定模型设置

使用以下命令为特定群组设置模型（需要超级用户权限）：

```
/总结配置 模型 设置 <Provider/Model> [-g 群号]
```

例如：
```
/总结配置 模型 设置 Gemini/gemini-2.0-flash  # 设置当前群
/总结配置 模型 设置 DeepSeek/deepseek-chat -g 123456  # 设置指定群
```

#### 移除群组特定模型

使用以下命令移除群组特定模型设置，恢复使用全局模型（需要超级用户权限）：

```
/总结配置 模型 移除 [-g 群号]
```

例如：
```
/总结配置 模型 移除  # 移除当前群的特定模型设置
/总结配置 模型 移除 -g 123456  # 移除指定群的特定模型设置
```

#### 查看可用模型

使用以下命令查看所有可用模型：

```
总结模型列表
```

或者使用统一配置入口：

```
/总结配置 模型 列表
```

输出示例：
```
可用 AI 模型列表 (格式: ProviderName/ModelName)：

Provider: DeepSeek
  API Keys: [2 个密钥]
  - deepseek-chat [当前激活] [默认]
  - deepseek-reasoner

Provider: Gemini
  - gemini-2.0-flash
  - gemini-2.5-flash-preview-04-17

Provider: GLM
  - glm-4-flash

使用 '总结切换模型 ProviderName/ModelName' 来切换当前激活模型 (仅限超级用户)。
```

#### 查看群组配置

使用以下命令查看群组的当前配置：

```
/总结配置 查看 [-g 群号]
```

不带参数直接输入 `/总结配置` 效果相同。

输出示例：
```
群聊 123456789 的总结配置信息：

当前使用模型： Gemini/gemini-2.0-flash (群组特定设置)
全局默认模型： DeepSeek/deepseek-chat
默认总结风格： 简洁明了

定时总结任务： 已设置 (22:30, 最少消息数: 500)
```

### 支持的 API 类型

插件支持多种 API 类型，通常会根据模型名称自动推断，但也可以显式指定：

- `gemini`: Google Gemini API
- `openai`: OpenAI API 和兼容 OpenAI 接口的服务
- `claude`: Anthropic Claude API
- `deepseek`: DeepSeek API
- `mistral`: Mistral AI API
- `zhipu`: 智谱 GLM API
- `xunfei`: 讯飞星火 API
- `baidu`: 百度文心一言 API
- `qwen`: 阿里通义千问 API

如果模型名称不足以推断 API 类型，建议显式指定 `api_type` 字段。

### 如何获取各大模型的 API 密钥

下面是获取常用 AI 模型 API 密钥的方法：

#### DeepSeek
1. 访问 [DeepSeek 官网](https://platform.deepseek.com/)
2. 注册并登录账号
3. 在控制台中找到 API Keys 选项
4. 创建新的 API Key，格式为 `sk-` 开头

#### GLM (智谱 AI)
1. 访问 [智谱 AI 开放平台](https://open.bigmodel.cn/)
2. 注册并登录账号
3. 在控制台中找到 API Keys 管理
4. 创建新的 API Key，通常包含两部分（API Key 和 Secret Key）
5. 将两部分用点号连接起来，如 `api_key.secret_key`

#### Gemini
1. 访问 [Google AI Studio](https://makersuite.google.com/app/apikey)
2. 使用 Google 账号登录
3. 点击 "Get API key" 或类似按钮
4. 创建新的 API Key，格式为 `AIzaSy` 开头

#### ARK (火山方舟)
1. 访问 [火山方舟模型](https://console.volcengine.com/ark/region:ark+cn-beijing)
2. 注册并登录账号
3. 在控制台中找到 API Keys 管理
4. 创建新的 API Key，通常是 UUID 格式

#### OpenAI 兼容服务
如果使用第三方 OpenAI 兼容服务（如 API2D、OhMyGPT 等）：
1. 访问相应的服务商网站
2. 注册并充值
3. 获取 API Key
4. 在配置中将 `api_type` 设置为 `openai`
5. 将 `api_base` 设置为相应的服务地址

## 功能演示

### 基础总结功能
<details>
<summary>点击展开查看示例</summary>

**输入：**
```
总结 100
```

**输出：**
```
【最近100条消息总结】
1. 用户们讨论了最近的游戏更新，主要关注新增的角色系统
2. 有几位成员分享了自己的游戏攻略和心得
3. 话题逐渐转向了服务器维护相关问题
4. 最后讨论了周末活动的安排

分析：整体讨论氛围积极，主要围绕游戏内容和社群活动展开。
```
</details>

### 定向总结功能
<details>
<summary>点击展开查看示例</summary>

**输入：**
```
总结 200 @张三 关于项目进度
```

**输出：**
```
【张三的项目进度相关发言总结】
1. 完成了数据库优化工作，查询性能提升30%
2. 修复了3个关键性bug，详见issue#123
3. 新功能开发按计划推进，预计下周完成
4. 提出了几个改进建议，已在团队内讨论

分析：工作进展顺利，按计划推进，并有额外的优化成果。
```
</details>

### 定时总结功能
<details>
<summary>点击展开查看示例</summary>

**设置：**
```
定时总结 22:00 500
```

**每天22:00自动输出：**
```
【今日群聊总结】
1. 上午主要讨论了...
2. 下午话题集中在...
3. 晚间讨论了...

今日活跃度分析：
- 总发言量：500条
- 热门话题：xxx
- 活跃时段：20:00-21:00
```
</details>

### 自定义风格总结
<details>
<summary>点击展开查看示例</summary>

**输入：**
```
总结 100 -p 锐评
```

**输出：**
```
【群友行为大赏】
1. 某群友疯狂水表情包，堪称表情包大师
2. 有人沉迷摸鱼，工作都是浮云
3. 吃瓜群众围观吃瓜，好不热闹
4. 最后都在畅想发工资，真实

点评：群友都是人才，说话又好笑。
```
</details>

## 使用建议与最佳实践

### 总结效果优化

1. **消息数量范围**：合理设置消息数量范围，建议保持在 100-500 条之间获得最佳效果
2. **关键词过滤**：针对特定话题总结时，使用关键词过滤，如 `总结 200 关于项目进度`
3. **风格选择**：根据不同场景选择适合的总结风格，如正式场合选择 `正式`，休闲聊天选择 `幽默` 或 `锐评`
4. **模型选择**：不同模型对不同类型的内容有各自的优势，可以尝试切换模型比较效果

### 定时总结优化

1. **时间选择**：使用定时总结功能时，选择群内较为空闲的时间段，如晚上 22:00 或中午 12:00
2. **消息数量设置**：定时总结建议设置较大的消息数量，如 500-1000 条，以涵盖更长时间的讨论
3. **风格设置**：定时总结可以设置固定风格，如 `定时总结 22:00 500 -p 日报风格`

### 系统维护

1. **定期检查**：定期使用 `总结健康检查` 命令检查系统状态
2. **问题修复**：如遇系统异常，使用 `总结系统修复` 命令尝试自动修复
3. **调度状态**：使用 `总结调度状态` 命令查看定时任务运行情况

### 模型管理

1. **分群设置**：为不同群组设置不同的模型，根据群的特点和讨论内容选择最适合的模型
2. **API 密钥轮询**：对于高频率使用的模型，建议配置多个 API 密钥进行轮询，减少单个密钥的负载
3. **模型参数调整**：根据需要调整模型的 temperature 和 max_tokens 参数，以得到更符合预期的总结效果

### 风格设置与管理

#### 全局风格设置

在总结命令中可以使用 `-p` 参数指定风格：

```
总结 <消息数量> -p <风格>
```

常用风格示例：
- **正式**：适合工作汇报、会议记录等正式场合
- **简洁**：简洁明了的总结风格，只包含要点
- **幽默**：带有幽默感的总结，适合休闲聊天
- **锐评**：尖锐广东话风格的评论，带有广东话特色
- **日报**：类似工作日报的格式，适合定时总结

例如：
```
总结 300 -p 正式
总结 200 -p 锐评
```

#### 群组风格设置

使用以下命令为群组设置默认总结风格（需要管理员权限）：

```
/总结配置 风格 设置 <风格名称> [-g 群号]
```

例如：
```
/总结配置 风格 设置 简洁明了  # 设置当前群
/总结配置 风格 设置 幽默 -g 123456  # 设置指定群
```

#### 移除群组风格设置

使用以下命令移除群组的默认风格设置（需要管理员权限）：

```
/总结配置 风格 移除 [-g 群号]
```

例如：
```
/总结配置 风格 移除  # 移除当前群的风格设置
/总结配置 风格 移除 -g 123456  # 移除指定群的风格设置
```

注意：设置群组默认风格后，在该群使用总结命令时将自动应用该风格，除非手动指定了其他风格。

## 常见问题

### 1. API 调用失败

**问题现象：**
- 总结命令返回“调用 API 失败”类似错误
- 日志中出现 API 连接超时或认证失败

**解决方法：**
- 检查 API 密钥是否正确配置，包括格式和有效性
- 确认网络代理设置（如果需要），尤其是使用 Gemini 等国外模型时
- 查看错误日志获取详细信息，通常在 `zhenxun_bot/logs` 目录下
- 尝试切换到其他模型，使用 `总结切换模型` 命令

### 2. 定时任务未执行

**问题现象：**
- 设置了定时总结但在指定时间没有触发

**解决方法：**
- 检查时间格式是否正确（支持 HH:MM 或 HHMM 格式）
- 使用 `总结调度状态` 命令查看任务是否已正确注册
- 确认 Bot 运行状态，如果 Bot 在计划时间点不在线则任务不会执行
- 使用 `总结健康检查` 检查调度器组件是否正常
- 如有必要，使用 `总结系统修复` 尝试修复调度器问题

### 3. 总结质量问题

**问题现象：**
- 总结内容质量不理想，如太简单、不准确或不相关

**解决方法：**
- 调整消息数量范围，建议在 100-500 条之间获得最佳效果
- 使用更精确的关键词过滤，如 `总结 200 关于项目进度`
- 尝试不同的总结风格，如 `总结 300 -p 正式` 或 `总结 300 -p 简洁`
- 切换到不同的 AI 模型，不同模型对不同类型的内容有各自的优势

### 4. 模型配置问题

**问题现象：**
- 无法正确切换模型
- 配置文件中的模型设置不生效

**解决方法：**
- 确保模型名称格式正确，必须使用 `ProviderName/ModelName` 格式
- 检查配置文件中的 `SUMMARY_PROVIDERS` 结构是否正确
- 使用 `总结模型列表` 命令查看当前可用的模型
- 如果修改了配置文件，需要重启 Bot 才能生效


## 技术支持

如遇到问题，请：
1. 查看 Bot 日志获取错误信息
2. 使用`总结健康检查`命令诊断系统状态
3. 提交 Issue 到项目仓库

## 致谢

特别感谢：

- [nonebot_plugin_summary_group](https://github.com/StillMisty/nonebot_plugin_summary_group) - 本项目的原始版本，由 [@StillMisty](https://github.com/StillMisty) 开发
- [Zhenxun Bot](https://github.com/HibiKier/zhenxun_bot) - 强大的机器人框架
- [NoneBot2](https://github.com/nonebot/nonebot2) - 优秀的机器人框架
- 所有贡献者和用户

## 许可证

本项目采用 MIT 许可证。详见 LICENSE 文件。

原项目 [nonebot_plugin_summary_group](https://github.com/StillMisty/nonebot_plugin_summary_group) 采用 Apache-2.0 许可证。

---

