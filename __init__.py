from nonebot import get_driver, require

driver = get_driver()
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, PrivateMessageEvent
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot_plugin_alconna.uniseg import MsgTarget, UniMessage

from zhenxun.configs.config import Config
from zhenxun.configs.utils import PluginCdBlock, PluginExtraData, RegisterConfig
from zhenxun.services.log import logger
from zhenxun.utils.enum import LimitWatchType, PluginLimitType
from zhenxun.utils.rules import admin_check, is_allowed_call

require("nonebot_plugin_alconna")
from arclet.alconna import (
    Alconna,
    Args,
    CommandMeta,
    Field,
    MultiVar,
    Option,
    Subcommand,
)
from nonebot_plugin_alconna import (
    At,
    CommandResult,
    Match,
    Text,
    on_alconna,
)

base_config = Config.get("summary_group")

from .config import summary_config  # noqa: F401


def validate_msg_count_range(count: int) -> int:
    """验证消息数量是否在配置的范围内"""
    logger.debug(f"--- 验证器 validate_msg_count_range 被调用，输入参数: {count} ---")

    min_len_val = base_config.get("SUMMARY_MIN_LENGTH")
    max_len_val = base_config.get("SUMMARY_MAX_LENGTH")

    if min_len_val is None or max_len_val is None:
        logger.error(
            "配置缺失: SUMMARY_MIN_LENGTH 或 SUMMARY_MAX_LENGTH 未在配置中找到或为 null。"
        )
        raise ValueError("配置错误: 缺少最小/最大消息长度设置。")

    try:
        min_len_int = int(min_len_val)
        max_len_int = int(max_len_val)
    except (ValueError, TypeError):
        logger.error("配置值 SUMMARY_MIN_LENGTH 或 SUMMARY_MAX_LENGTH 不是有效整数。")
        raise ValueError("配置错误: 最小/最大消息长度不是有效整数。")

    if not (min_len_int <= count <= max_len_int):
        logger.warning(
            f"消息数量验证失败: {count} 不在范围 [{min_len_int}, {max_len_int}] 内"
        )
        raise ValueError(f"总结消息数量应在 {min_len_int} 到 {max_len_int} 之间")

    return count


def parse_and_validate_time(time_str: str) -> tuple[int, int]:
    logger.debug(f"--- parse_and_validate_time 被调用，输入参数: {time_str!r} ---")

    try:
        from .handlers.scheduler import parse_time

        result = parse_time(time_str)
        logger.debug(
            f"parse_and_validate_time 执行成功，结果: {result[0]:02d}:{result[1]:02d}"
        )
        return result

    except ValueError as e:
        logger.error(f"parse_and_validate_time 执行失败: {e}", e=e)
        raise

    except Exception as e:
        logger.error(f"parse_and_validate_time 意外错误: {e}", e=e)
        raise ValueError(f"解析时间时发生意外错误: {e}")


TIME_REGEX = r"(0?[0-9]|1[0-9]|2[0-3]):([0-5][0-9])|(0?[0-9]|1[0-9]|2[0-3])([0-5][0-9])"


__plugin_meta__ = PluginMetadata(
    name="群聊总结",
    description="使用 AI 分析群聊记录，生成讨论内容的总结",
    usage=(
        "📖 **群聊总结插件**\n\n"
        "🔍 **核心功能 (所有用户)**\n"
        "  `总结 <数量>` - 对最近消息进行总结\n"
        "  `总结 <数量> @用户` - 总结特定用户的发言\n"
        "  `总结 <数量> <关键词>` - 总结含特定关键词的消息\n"
        "  `总结 <数量> -p <风格>` - 指定本次总结的风格\n"
        "  *(超级用户可追加 `-g <群号>` 指定任意群聊)*\n\n"
        "⏱️ **定时总结 (管理员及以上)**\n"
        "  `定时总结 <时间> [数量] [-p <风格>]` - 为本群设置每日定时总结\n"
        "  `定时总结取消` - 取消本群的定时总结任务\n"
        "  *(时间格式: HH:MM 或 HHMM)*\n"
        "  *(超级用户可追加 `-g <群号>` 或 `-all`)*\n\n"
        "⚙️ **群组配置 (管理员及以上)**\n"
        "  `总结配置` - 查看本群的总结配置\n"
        "  `总结配置 风格 设置 <风格>` - 设置本群的默认总结风格\n"
        "  `总结配置 风格 移除` - 移除本群的默认总结风格\n"
        "  `总结配置 模型 设置 <模型>` - **(仅超管)** 设置本群的默认模型\n"
        "  `总结配置 模型 移除` - **(仅超管)** 移除本群的默认模型\n"
        "  *(超级用户可追加 `-g <群号>` 指定任意群聊)*\n\n"
        "🤖 **全局配置 (仅超级用户)**\n"
        "  `总结模型 列表` - 查看所有可用的AI模型\n"
        "  `总结模型 设置 <模型>` - 设置插件的全局默认AI模型\n"
        "  `总结风格 设置 <风格>` - 设置插件的全局默认风格\n"
        "  `总结风格 移除` - 移除插件的全局默认风格\n\n"
        "ℹ️ **说明**\n"
        f"  • 消息数量范围: {base_config.get('SUMMARY_MIN_LENGTH', 1)}-{base_config.get('SUMMARY_MAX_LENGTH', 1000)}\n"
        f"  • 手动总结冷却: {base_config.get('SUMMARY_COOL_DOWN', 60)}秒"
    ),
    type="application",
    homepage="https://github.com/webjoin111/zhenxun_plugin_summary_group",
    supported_adapters={"~onebot.v11"},
    extra=PluginExtraData(
        author="webjoin111",
        version="3.0",
        configs=[
            RegisterConfig(
                module="summary_group",
                key="MESSAGE_CACHE_TTL_SECONDS",
                value=300,
                help="获取的消息列表缓存时间（秒），0表示禁用缓存，每次都实时获取。",
                default_value=300,
                type=int,
            ),
            RegisterConfig(
                module="summary_group",
                key="SUMMARY_MAX_LENGTH",
                value=1000,
                help="手动触发总结时，默认获取的最大消息数量",
                default_value=1000,
                type=int,
            ),
            RegisterConfig(
                module="summary_group",
                key="SUMMARY_MIN_LENGTH",
                value=50,
                help="触发总结所需的最少消息数量",
                default_value=50,
                type=int,
            ),
            RegisterConfig(
                module="summary_group",
                key="SUMMARY_COOL_DOWN",
                value=60,
                help="用户手动触发总结的冷却时间（秒，0表示无冷却）",
                default_value=60,
                type=int,
            ),
            RegisterConfig(
                module="summary_group",
                key="summary_output_type",
                value="image",
                help="总结输出类型 (image 或 text)",
                default_value="image",
                type=str,
            ),
            RegisterConfig(
                module="summary_group",
                key="summary_fallback_enabled",
                value=False,
                help="当图片生成失败时是否自动回退到文本模式",
                default_value=False,
                type=bool,
            ),
            RegisterConfig(
                module="summary_group",
                key="summary_theme",
                value="dark",
                help="总结图片输出的主题 (可选: light, dark, cyber)",
                default_value="dark",
                type=str,
            ),
            RegisterConfig(
                module="summary_group",
                key="EXCLUDE_BOT_MESSAGES",
                value=False,
                help="是否在总结时排除 Bot 自身发送的消息",
                default_value=False,
                type=bool,
            ),
            RegisterConfig(
                module="summary_group",
                key="USE_DB_HISTORY",
                value=False,
                help="是否尝试从数据库(chat_history表)读取聊天记录",
                default_value=False,
                type=bool,
            ),
            RegisterConfig(
                module="summary_group",
                key="SUMMARY_MODEL_NAME",
                value="Gemini/gemini-2.5-flash",
                help="默认使用的 AI 模型名称 (格式: ProviderName/ModelName)",
                default_value="Gemini/gemini-2.5-flash",
                type=str,
            ),
            RegisterConfig(
                module="summary_group",
                key="SUMMARY_DEFAULT_STYLE",
                value=None,
                help="全局默认的总结风格，会被分群设置覆盖。",
                default_value=None,
                type=str,
            ),
            RegisterConfig(
                module="summary_group",
                key="ENABLE_AVATAR_ENHANCEMENT",
                value=True,
                help="是否启用头像增强功能",
                default_value=True,
                type=bool,
            ),
        ],
        limits=[
            PluginCdBlock(
                cd=60,
                limit_type=PluginLimitType.CD,
                watch_type=LimitWatchType.USER,
                status=True,
                result="总结功能冷却中，请等待 {cd} 后再试~",
            )
        ],
    ).dict(),
)


summary_group = on_alconna(
    Alconna(
        "总结",
        Args[
            "message_count",
            int,
            Field(
                completion=lambda: f"输入消息数量 ({base_config.get('SUMMARY_MIN_LENGTH', 1)}-{base_config.get('SUMMARY_MAX_LENGTH', 1000)})",
            ),
        ],
        Option(
            "-p|--prompt",
            Args["style", str, Field(completion="指定总结风格，如：锐评, 正式")],
        ),
        Option(
            "-g",
            Args[
                "target_group_id", int, Field(completion="指定群号 (需要超级用户权限)")
            ],
        ),
        Args[
            "parts?",
            MultiVar(At | Text),
            Field(default=[], completion="可以@用户 或 输入要过滤的关键词"),
        ],
        meta=CommandMeta(
            compact=True,
            strict=False,
            description="生成群聊总结",
            usage=(
                "总结 <消息数量> [-p|--prompt 风格] [-g 群号] [@用户/内容过滤...]\n"
                "消息数量范围: "
                f"{base_config.get('SUMMARY_MIN_LENGTH', 1)} - "
                f"{base_config.get('SUMMARY_MAX_LENGTH', 1000)}\n"
                "说明: -g 仅限超级用户"
            ),
        ),
    ),
    rule=is_allowed_call(),
    priority=5,
    block=True,
)

summary_set = on_alconna(
    Alconna(
        "定时总结",
        Args["time_str", str, Field(completion="输入定时时间 (HH:MM 或 HHMM)")],
        Args[
            "least_message_count?",
            int,
            Field(
                default=base_config.get("SUMMARY_MAX_LENGTH", 1000),
                completion="输入定时总结所需的最少消息数量 (可选)",
            ),
        ],
        Option(
            "-p|--prompt",
            Args["style", str, Field(completion="指定总结风格，如：锐评, 正式 (可选)")],
        ),
        Option(
            "-g",
            Args[
                "target_group_id", int, Field(completion="指定群号 (需要超级用户权限)")
            ],
        ),
        Option("-all", help_text="对所有群生效 (需要超级用户权限)"),
        meta=CommandMeta(
            description="设置定时群聊总结",
            usage=(
                "定时总结 <时间> [最少消息数量] [-p|--prompt 风格] [-g 群号 | -all]\n"
                "时间格式: HH:MM 或 HHMM\n"
                "说明: 设置本群需管理员, -g/-all 仅限超级用户"
            ),
            compact=True,
        ),
    ),
    rule=admin_check("summary_group", "SUMMARY_ADMIN_LEVEL"),
    priority=5,
    block=True,
)


summary_remove = on_alconna(
    Alconna(
        "定时总结取消",
        Option(
            "-g",
            Args[
                "target_group_id", int, Field(completion="指定群号 (需要超级用户权限)")
            ],
        ),
        Option("-all", help_text="取消所有群的定时总结 (需要超级用户权限)"),
        meta=CommandMeta(
            description="取消定时群聊总结",
            usage="定时总结取消 [-g 群号 | -all]\n说明: 取消本群需管理员",
            example="定时总结取消\n定时总结取消 -g 123456\n定时总结取消 -all",
        ),
    ),
    rule=admin_check("summary_group", "SUMMARY_ADMIN_LEVEL"),
    priority=4,
    block=True,
)


summary_model_cmd = on_alconna(
    Alconna(
        "总结模型",
        Subcommand("列表", help_text="查看可用AI模型列表"),
        Subcommand(
            "设置", Args["provider_model", str], help_text="设置本插件全局默认模型"
        ),
        meta=CommandMeta(
            description="管理总结插件的全局默认AI模型",
            usage="总结模型 列表\n总结模型 设置 <Provider/Model>",
        ),
    ),
    permission=SUPERUSER,
    priority=5,
    block=True,
)

summary_style_cmd = on_alconna(
    Alconna(
        "总结风格",
        Subcommand("设置", Args["style_name", str], help_text="设置本插件全局默认风格"),
        Subcommand("移除", help_text="移除全局默认风格"),
        meta=CommandMeta(
            description="管理总结插件的全局默认风格",
            usage="总结风格 设置 <风格名称>\n总结风格 移除",
        ),
    ),
    permission=SUPERUSER,
    priority=5,
    block=True,
)

summary_config_cmd = on_alconna(
    Alconna(
        "总结配置",
        Option("-g", Args["target_group_id?", int], help_text="指定群号(仅超级用户)"),
        Subcommand(
            "模型", Subcommand("设置", Args["provider_model", str]), Subcommand("移除")
        ),
        Subcommand(
            "风格", Subcommand("设置", Args["style_name", str]), Subcommand("移除")
        ),
        meta=CommandMeta(
            description="管理本群或指定群的总结配置",
            usage=(
                "总结配置 (查看本群配置)\n"
                "总结配置 模型 设置 <Provider/Model> (为本群设置模型, 仅超管)\n"
                "总结配置 模型 移除 (移除本群特定模型, 仅超管)\n"
                "总结配置 风格 设置 <风格名称> (为本群设置风格, 需管理)\n"
                "总结配置 风格 移除 (移除本群特定风格, 需管理)\n"
            ),
        ),
    ),
    priority=5,
    block=True,
)


from .handlers.group_settings import (
    handle_global_model_setting,
    handle_global_style_setting,
    handle_group_specific_config,
)
from .handlers.scheduler import (
    handle_summary_remove as summary_remove_handler_impl,
)
from .handlers.scheduler import (
    handle_summary_set as summary_set_handler_impl,
)
from .handlers.summary import handle_summary as summary_handler_impl


@summary_group.handle()
async def _(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent,
    result: CommandResult,
    message_count: int,
    style: Match[str],
    parts: Match[list[At | Text]],
    target: MsgTarget,
):
    user_id_str = event.get_user_id()
    is_superuser = await SUPERUSER(bot, event)

    try:
        validate_msg_count_range(message_count)
        logger.debug(f"消息数量 {message_count} 范围验证通过。")
    except ValueError as e:
        logger.warning(f"消息数量验证失败 (Handler): {e}")
        await UniMessage.text(str(e)).send(target)
        return

    logger.debug(
        f"用户 {user_id_str} 触发总结，权限、冷却和参数验证通过 (或为 Superuser)，开始执行核心逻辑。"
    )

    arp = result.result
    target_group_id_match = arp.query("g.target_group_id") if arp else None
    if target_group_id_match and not is_superuser:
        await UniMessage.text("需要超级用户权限才能使用 -g 参数指定群聊。").send(target)
        logger.warning(f"用户 {user_id_str} (非超级用户) 尝试使用 -g 参数")
        return

    try:
        await summary_handler_impl(
            bot, event, result, message_count, style, parts, target
        )
    except Exception as e:
        logger.error(
            f"处理总结命令时发生异常: {e}",
            command="总结",
            session=event.get_user_id(),
            group_id=getattr(event, "group_id", None),
        )
        try:
            await UniMessage.text(f"处理命令时出错: {e!s}").send(target)
        except Exception:
            logger.error("发送错误消息失败", command="总结")


@summary_set.handle()
async def _(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent,
    result: CommandResult,
    target: MsgTarget,
):
    try:
        arp = result.result
        if not arp:
            logger.error("在 summary_set handler 中 Arparma result 为 None")
            await UniMessage.text("命令解析内部错误，请重试或联系管理员。").send(target)
            return

        time_str_match = arp.query("time_str")
        least_count_match = arp.query("least_message_count")

        style_value = arp.query("p.style")
        if style_value is None:
            style_value = arp.query("prompt.style")
        logger.debug(f"使用 arp.query 提取的 style_value: {style_value!r}")

        if not time_str_match:
            await UniMessage.text("必须提供时间参数").send(target)
            return

        try:
            time_tuple = parse_and_validate_time(time_str_match)

            default_count = base_config.get("SUMMARY_MAX_LENGTH")
            count_to_validate = (
                least_count_match if least_count_match is not None else default_count
            )
            least_count = validate_msg_count_range(int(count_to_validate))

        except ValueError as e:
            await UniMessage.text(str(e)).send(target)
            return
        except Exception as e:
            logger.error(f"解析时间或数量时出错: {e}", command="定时总结")
            await UniMessage.text(f"解析时间或数量时出错: {e}").send(target)
            return

        await summary_set_handler_impl(
            bot, event, result, time_tuple, least_count, style_value, target
        )
    except Exception as e:
        logger.error(
            f"处理定时总结设置命令时发生异常: {e}",
            command="定时总结",
            session=event.get_user_id(),
            group_id=getattr(event, "group_id", None),
            e=e,
        )
        try:
            await UniMessage.text(f"处理命令时出错: {e!s}").send(target)
        except Exception:
            logger.error("发送错误消息失败", command="定时总结")


@summary_remove.handle()
async def _(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent,
    result: CommandResult,
    target: MsgTarget,
):
    await summary_remove_handler_impl(bot, event, result, target)


@summary_model_cmd.handle()
async def _(
    event: GroupMessageEvent | PrivateMessageEvent,
    target: MsgTarget,
    result: CommandResult,
):
    await handle_global_model_setting(event.get_user_id(), target, result)


@summary_style_cmd.handle()
async def _(
    event: GroupMessageEvent | PrivateMessageEvent,
    target: MsgTarget,
    result: CommandResult,
):
    await handle_global_style_setting(event.get_user_id(), target, result)


@summary_config_cmd.handle()
async def _(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent,
    target: MsgTarget,
    result: CommandResult,
):
    await handle_group_specific_config(bot, event, target, result)
