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
  - [功能演示](#功能演示)
    - [基础总结功能](#基础总结功能)
    - [定向总结功能](#定向总结功能)
    - [定时总结功能](#定时总结功能)
    - [自定义风格总结](#自定义风格总结)
  - [使用建议](#使用建议)
  - [常见问题](#常见问题)
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

1. 设置定时总结：
```
定时总结 [HH:MM或HHMM] [最少消息数量] [-g 群号] [-all]
```

2. 取消定时总结：
```
定时总结取消 [-g 群号] [-all]
```

3. 查看调度状态：
```
总结调度状态 [-d]
```

4. 系统维护命令：
```
总结健康检查
总结系统修复
```

## 配置说明

在 Zhenxun Bot 的配置文件中添加以下配置项：

```yaml
summary_group:
  # API配置
  summary_api_keys: null  # API密钥列表或单个密钥
  summary_api_base: https://generativelanguage.googleapis.com  # API基础URL
  summary_model: gemini-2.0-flash-exp  # 使用的AI模型名称
  summary_api_type: null  # API类型(openai/claude/gemini/baidu等)
  summary_openai_compat: false  # 是否使用OpenAI兼容模式

  # 网络配置
  proxy: null  # 代理地址，如 http://127.0.0.1:7890
  time_out: 120  # API请求超时时间（秒）
  max_retries: 3  # 最大重试次数
  retry_delay: 2  # 重试延迟时间（秒）

  # 功能配置
  summary_max_length: 1000  # 单次总结最大消息数量
  summary_min_length: 50  # 触发总结最少消息数量
  summary_cool_down: 60  # 用户触发冷却时间（秒）
```

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

## 使用建议

1. 合理设置消息数量范围，建议保持在 50-1000 条之间
2. 使用定时总结功能时，建议选择群内较为空闲的时间段
3. 针对特定话题总结时，建议使用关键词过滤
4. 如遇系统异常，可使用健康检查和修复功能

## 常见问题

1. API 调用失败
   - 检查 API 密钥配置
   - 确认网络代理设置
   - 查看错误日志获取详细信息

2. 定时任务未执行
   - 检查时间格式是否正确
   - 使用`总结调度状态`命令查看任务状态
   - 确认 Bot 运行状态

3. 总结质量问题
   - 调整消息数量范围
   - 使用更精确的关键词过滤
   - 尝试不同的总结风格


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
