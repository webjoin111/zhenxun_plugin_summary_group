from pathlib import Path

from nonebot import get_driver, require

driver = get_driver()
from bs4 import BeautifulSoup
from markupsafe import Markup
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, PrivateMessageEvent
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot_plugin_alconna.uniseg import MsgTarget, UniMessage

from zhenxun.builtin_plugins.scheduler_admin.commands import schedule_cmd
from zhenxun.configs.config import Config
from zhenxun.configs.utils import PluginExtraData, RegisterConfig
from zhenxun.services import renderer_service
from zhenxun.services.log import logger

require("nonebot_plugin_alconna")
from nonebot_plugin_alconna import At, CommandResult, Match, Text

base_config = Config.get("summary_group")

from zhenxun.utils.depends import Cooldown, GetGroupConfig

from .commands import summary_config_cmd, summary_group
from .config import (
    GroupSettings,
    summary_config,  # noqa: F401
)
from .utils.message_processing import avatar_enhancer

renderer_service.register_template_namespace(
    "@summary_group", Path(__file__).parent / "templates"
)


@renderer_service.filter("enhance_avatars")
async def enhance_avatars_filter(html_content: str, user_info_cache: dict) -> Markup:
    """
    一个自定义的异步Jinja2过滤器，用于在渲染期间增强HTML中的头像。
    它接收由 `md` 过滤器生成的HTML，并返回处理后的HTML。
    """
    if not user_info_cache:
        return Markup(html_content)

    summary_text = BeautifulSoup(html_content, "html.parser").get_text()
    await avatar_enhancer.enhance_summary_with_avatars(summary_text, user_info_cache)
    return Markup(
        avatar_enhancer.enhance_html_with_markup(
            html_content, user_info_cache, mode="avatar"
        )
    )


def validate_msg_count_range(count: int | str) -> int | str:
    """验证消息数量是否在配置的范围内"""
    if not isinstance(count, int):
        return count

    min_len_val = base_config.get("SUMMARY_MIN_LENGTH")
    max_len_val = base_config.get("SUMMARY_MAX_LENGTH")

    if min_len_val is None or max_len_val is None:
        logger.error(
            "配置缺失: SUMMARY_MIN_LENGTH 或 SUMMARY_MAX_LENGTH 未在配置中找到或为 null"
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
        "  `定时总结 开启 <时间>` - 为本群设置每日定时总结\n"
        "  `定时总结 删除` - 删除本群的定时总结任务\n"
        "  `定时总结 暂停` - 暂停本群的定时总结任务\n"
        "  `定时总结 恢复` - 恢复本群的定时总结任务\n"
        "  `定时总结 查看` - 查看本群的定时总结任务\n"
        "  *(时间格式: HH:MM)*\n"
        "  *(超级用户可追加 `-g <群号>` 或 `--all`)*\n\n"
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
        f"  • 消息数量范围: {base_config.get('SUMMARY_MIN_LENGTH', 1)}-"
        f"{base_config.get('SUMMARY_MAX_LENGTH', 1000)}\n"
        f"  • 手动总结冷却: {base_config.get('SUMMARY_COOL_DOWN', 5)}分钟"
    ),
    type="application",
    homepage="https://github.com/webjoin111/zhenxun_plugin_summary_group",
    supported_adapters={"~onebot.v11"},
    extra=PluginExtraData(
        author="webjoin111",
        version="3.1.0",
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
                value=5,
                help="用户手动触发总结的冷却时间（分钟，0表示无冷却）",
                default_value=5,
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
        group_config_model=GroupSettings,
    ).dict(),
)


schedule_cmd.shortcut(
    r"^定时总结 开启 (?P<time>\S+)(?:\s+(?P<summary_args>.*?))?(?:\s+(?P<target>-g\s+[\d\s]+|-t\s+\S+))?$",  # noqa: E501
    command="定时任务",
    arguments=[
        "设置",
        "summary_group",
        "{target}",
        "--daily",
        "{time}",
        "--params-cli",
        '"{summary_args}"',
    ],
    prefix=True,
)

schedule_cmd.shortcut(
    r"^定时总结 (?P<action>关闭|删除)"
    r"(?:\s+(?P<target>--all|-g\s+[\d\s]+|-t\s+\S+))?$",
    command="定时任务",
    arguments=["{action}", "{target}", "-p", "summary_group"],
    prefix=True,
)

schedule_cmd.shortcut(
    r"^定时总结 (?P<action>暂停|恢复|查看)"
    r"(?:\s+(?P<target>--all|-g\s+[\d\s]+|-t\s+\S+))?$",
    command="定时任务",
    arguments=["{action}", "{target}", "-p", "summary_group"],
    prefix=True,
)

schedule_cmd.shortcut(
    r"^全局定时总结 (?P<action>开启) (?P<time>\S+)$",
    command="定时任务",
    arguments=["设置", "summary_group", "--global", "--daily", "{time}"],
    prefix=True,
)

schedule_cmd.shortcut(
    r"^全局定时总结 (?P<action>关闭|删除|暂停|恢复|查看)$",
    command="定时任务",
    arguments=["{action}", "--global", "-p", "summary_group"],
    prefix=True,
)


from .handlers.group_settings import (
    handle_group_specific_config,
)
from .handlers.summary import handle_summary as summary_handler_impl


@summary_group.handle(
    [
        Cooldown(
            f"{base_config.get('SUMMARY_COOL_DOWN', 5)}m",
            prompt="总结功能冷却中，请等待 {cd_str} 后再试~",
        )
    ]
)
async def _(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent,
    result: CommandResult,
    message_count: int | str,
    style: Match[str],
    parts: Match[list[At | Text]],
    target: MsgTarget,
    group_config: GroupSettings = GetGroupConfig(GroupSettings),
):
    user_id_str = event.get_user_id()
    is_superuser = await SUPERUSER(bot, event)

    try:
        if isinstance(message_count, str):
            if message_count.isdigit():
                message_count = int(message_count)
            elif message_count != "当天":
                await UniMessage.text("消息数量应为整数或'当天'。").send(target)
                return
        validate_msg_count_range(message_count)
        logger.debug(f"消息数量 {message_count} 范围验证通过。")
    except ValueError as e:
        logger.warning(f"消息数量验证失败 (Handler): {e}")
        await UniMessage.text(str(e)).send(target)
        return

    logger.debug(
        f"用户 {user_id_str} 触发总结，权限、冷却和参数验证通过 (或为 Superuser)，"
        f"开始执行核心逻辑。"
    )

    arp = result.result
    target_group_id_match = arp.query("g.target_group_id") if arp else None
    if target_group_id_match and not is_superuser:
        await UniMessage.text("需要超级用户权限才能使用 -g 参数指定群聊。").send(target)
        logger.warning(f"用户 {user_id_str} (非超级用户) 尝试使用 -g 参数")
        return

    try:
        await summary_handler_impl(
            bot, event, result, message_count, style, parts, target, group_config
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


@summary_config_cmd.handle()
async def _(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent,
    target: MsgTarget,
    result: CommandResult,
):
    await handle_group_specific_config(bot, event, target, result)
