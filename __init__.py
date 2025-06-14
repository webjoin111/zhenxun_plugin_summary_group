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
from zhenxun.utils.rules import admin_check
from zhenxun.utils.utils import FreqLimiter

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

require("nonebot_plugin_apscheduler")

base_config = Config.get("summary_group")
ai_config = Config.get("AI")

from .config import summary_config
from .utils.scheduler_tasks import set_scheduler

try:
    cooldown_seconds = base_config.get("SUMMARY_COOL_DOWN", 60)
    if not isinstance(cooldown_seconds, int) or cooldown_seconds < 0:
        logger.warning("配置项 SUMMARY_COOL_DOWN 值无效，使用 60")
        cooldown_seconds = 60
except Exception as e:
    logger.error(f"读取 SUMMARY_COOL_DOWN 配置失败: {e}，使用 60")
    cooldown_seconds = 60

summary_cd_limiter = FreqLimiter(cooldown_seconds)
logger.info(f"群聊总结插件冷却限制器已初始化，冷却时间: {cooldown_seconds} 秒")


def validate_msg_count_range(count: int) -> int:
    """验证消息数量是否在配置的范围内"""
    logger.debug(f"--- Validator validate_msg_count_range called with input: {count} ---")

    min_len_val = base_config.get("SUMMARY_MIN_LENGTH")
    max_len_val = base_config.get("SUMMARY_MAX_LENGTH")

    if min_len_val is None or max_len_val is None:
        logger.error("配置缺失: SUMMARY_MIN_LENGTH 或 SUMMARY_MAX_LENGTH 未在配置中找到或为 null。")
        raise ValueError("配置错误: 缺少最小/最大消息长度设置。")

    try:
        min_len_int = int(min_len_val)
        max_len_int = int(max_len_val)
    except (ValueError, TypeError):
        logger.error("配置值 SUMMARY_MIN_LENGTH 或 SUMMARY_MAX_LENGTH 不是有效整数。")
        raise ValueError("配置错误: 最小/最大消息长度不是有效整数。")

    if not (min_len_int <= count <= max_len_int):
        logger.warning(f"消息数量验证失败: {count} 不在范围 [{min_len_int}, {max_len_int}] 内")
        raise ValueError(f"总结消息数量应在 {min_len_int} 到 {max_len_int} 之间")

    return count


def parse_and_validate_time(time_str: str) -> tuple[int, int]:
    logger.debug(f"--- parse_and_validate_time called with input: {time_str!r} ---")

    try:
        from .handlers.scheduler import parse_time

        result = parse_time(time_str)
        logger.debug(f"parse_and_validate_time successful, result: {result[0]:02d}:{result[1]:02d}")
        return result

    except ValueError as e:
        logger.error(f"parse_and_validate_time failed: {e}", e=e)
        raise

    except Exception as e:
        logger.error(f"parse_and_validate_time unexpected error: {e}", e=e)
        raise ValueError(f"解析时间时发生意外错误: {e}")


TIME_REGEX = r"(0?[0-9]|1[0-9]|2[0-3]):([0-5][0-9])|(0?[0-9]|1[0-9]|2[0-3])([0-5][0-9])"


__plugin_meta__ = PluginMetadata(
    name="群聊总结",
    description="使用 AI 分析群聊记录，生成讨论内容的总结",
    usage=(
        "📖 **群聊总结插件**\n\n"
        "🔍 **基础命令**\n"
        "  • `总结 <消息数量>` - 总结最近的群聊消息\n"
        "  • `总结 <消息数量> -p <风格>` - 指定总结风格\n"
        "  • `总结 <消息数量> @用户` - 只总结特定用户的消息\n"
        "  • `总结模型列表` - 查看可用的AI模型\n"
        "  • `总结切换模型 <Provider/Model>` - 切换AI模型 (限超管)\n"
        "  • `总结密钥状态` - 查看API密钥状态 (限超管)\n\n"
        "⏱️ **定时功能**\n"
        "  • `定时总结 <时间>` - 设置定时总结 (需管理员)\n"
        "  • `定时总结取消` - 取消定时总结\n\n"
        "⚙️ **配置管理**\n"
        "  • `/总结配置` - 查看和管理总结设置\n\n"
        "ℹ️ **提示**\n"
        f"  • 消息数量范围: {base_config.get('SUMMARY_MIN_LENGTH', 1)}-{base_config.get('SUMMARY_MAX_LENGTH', 1000)}\n"
        f"  • 冷却时间: {base_config.get('SUMMARY_COOL_DOWN', 60)} 秒\n\n"
        "📋 更多详细帮助请使用 `总结帮助` 命令查看"
    ),
    type="application",
    homepage="https://github.com/webjoin111/zhenxun_plugin_summary_group",
    supported_adapters={"~onebot.v11"},
    extra=PluginExtraData(
        author="webjoin111",
        version="2.2",
        configs=[
            RegisterConfig(
                module="AI",
                key="PROVIDERS",
                value=[
                    {
                        "name": "DeepSeek",
                        "api_key": "sk-******",
                        "api_base": "https://api.deepseek.com",
                        "models": [
                            {
                                "model_name": "deepseek-chat",
                                "max_tokens": 4096,
                                "temperature": 0.7,
                            },
                            {"model_name": "deepseek-reasoner"},
                        ],
                    },
                    {
                        "name": "GLM",
                        "api_key": "**********.***********",
                        "api_base": "https://open.bigmodel.cn/api/paas",
                        "api_type": "zhipu",
                        "models": [
                            {
                                "model_name": "glm-4-flash",
                                "max_tokens": 4096,
                                "temperature": 0.7,
                            }
                        ],
                    },
                    {
                        "name": "ARK",
                        "api_key": "********-****-****-****-************",
                        "api_base": "https://ark.cn-beijing.volces.com/api/v3",
                        "api_type": "openai",
                        "models": [{"model_name": "ep-202503210****-****"}],
                    },
                    {
                        "name": "Gemini",
                        "api_key": [
                            "AIzaSy*****************************",
                            "AIzaSy*****************************",
                            "AIzaSy*****************************",
                        ],
                        "api_base": "https://generativelanguage.googleapis.com",
                        "temperature": 0.8,
                        "models": [
                            {"model_name": "gemini-2.0-flash"},
                            {"model_name": "gemini-2.5-flash-preview-04-17"},
                        ],
                    },
                ],
                help="配置多个 AI 服务提供商及其模型信息 (列表)",
                default_value=[],
                type=list[dict],
            ),
            RegisterConfig(
                module="summary_group",
                key="CURRENT_ACTIVE_MODEL_NAME",
                value=None,
                help="当前激活使用的 AI 模型名称 (格式: ProviderName/ModelName)",
                default_value=None,
                type=str | None,
            ),
            RegisterConfig(
                module="summary_group",
                key="PROXY",
                value=None,
                help="网络代理地址，例如 http://127.0.0.1:7890",
                default_value=None,
                type=str | None,
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
                key="SUMMARY_ADMIN_LEVEL",
                value=10,
                help="设置定时总结所需的管理员等级",
                default_value=10,
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
                value="vscode_dark",
                help="总结图片输出的主题 (可选: light, dark, vscode_light, vscode_dark)",
                default_value="vscode_dark",
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
                help="是否尝试从数据库(chat_history表)读取聊天记录 (实验性功能)",
                default_value=False,
                type=bool,
            ),
            RegisterConfig(
                module="summary_group",
                key="SUMMARY_DEFAULT_MODEL_NAME",
                value="DeepSeek/deepseek-chat",
                help="默认使用的 AI 模型名称 (格式: ProviderName/ModelName)",
                default_value="DeepSeek/deepseek-chat",
                type=str,
            ),
            RegisterConfig(
                module="summary_group",
                key="ENABLE_AVATAR_ENHANCEMENT",
                value=False,
                help="是否启用头像增强功能",
                default_value=False,
                type=bool,
            ),
        ],
        limits=[
            PluginCdBlock(
                cd=base_config.get("SUMMARY_COOL_DOWN", 60),
                limit_type=PluginLimitType.CD,
                watch_type=LimitWatchType.USER,
                status=True,
                result="总结功能冷却中，请等待 {cd} 秒后再试~",
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
            Args["target_group_id", int, Field(completion="指定群号 (需要超级用户权限)")],
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
            Args["target_group_id", int, Field(completion="指定群号 (需要超级用户权限)")],
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
            Args["target_group_id", int, Field(completion="指定群号 (需要超级用户权限)")],
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


summary_check_status = on_alconna(
    Alconna(
        "总结调度状态",
        Option("-d", alias=["--detail", "--详细"], help_text="显示详细信息"),
        meta=CommandMeta(
            description="检查定时总结任务的调度器状态（仅限超级用户）",
            usage="总结调度状态 [-d/--detail/--详细]",
        ),
    ),
    permission=SUPERUSER,
    priority=5,
    block=True,
)


summary_health = on_alconna(
    Alconna(
        "总结健康检查",
        meta=CommandMeta(
            description="检查总结系统的健康状态（仅限超级用户）",
            usage="总结健康检查",
        ),
    ),
    permission=SUPERUSER,
    priority=5,
    block=True,
)


summary_repair = on_alconna(
    Alconna(
        "总结系统修复",
        meta=CommandMeta(
            description="尝试修复总结系统的问题（仅限超级用户）",
            usage="总结系统修复",
        ),
    ),
    permission=SUPERUSER,
    priority=5,
    block=True,
)


summary_switch_model = on_alconna(
    Alconna(
        "总结切换模型",
        Args["provider_model", str, Field(completion="输入 ProviderName/ModelName")],
        meta=CommandMeta(
            description="切换当前使用的 AI 模型 (仅限超级用户)",
            usage="总结切换模型 ProviderName/ModelName",
        ),
    ),
    permission=SUPERUSER,
    priority=5,
    block=True,
)

summary_list_models = on_alconna(
    Alconna(
        "总结模型列表",
        meta=CommandMeta(description="列出可用的 AI 模型", usage="总结模型列表"),
    ),
    priority=5,
    block=True,
)

summary_key_status = on_alconna(
    Alconna(
        "总结密钥状态",
        meta=CommandMeta(
            description="查看 API Key 的状态信息（仅限超级用户）",
            usage="总结密钥状态",
        ),
    ),
    permission=SUPERUSER,
    priority=5,
    block=True,
)

summary_help = on_alconna(
    Alconna(
        "总结帮助",
        meta=CommandMeta(
            description="显示总结插件的帮助文档",
            usage="总结帮助",
            example="总结帮助",
        ),
    ),
    priority=5,
    block=True,
)

summary_config_cmd = on_alconna(
    Alconna(
        "总结配置",
        Option("-g", Args["target_group_id?", int]),
        Subcommand(
            "模型",
            Subcommand("列表"),
            Subcommand("切换", Args["provider_model", str]),
            Subcommand("设置", Args["provider_model", str]),
            Subcommand("移除"),
        ),
        Subcommand(
            "风格",
            Subcommand("设置", Args["style_name", str]),
            Subcommand("移除"),
        ),
        Subcommand("查看"),
        meta=CommandMeta(
            description="管理总结插件的配置",
            usage=(
                "总结配置 [-g 群号]\n"
                "总结配置 模型 列表\n"
                "总结配置 模型 切换 <Provider/Model>  (仅 Superuser)\n"
                "总结配置 模型 设置 <Provider/Model> [-g 群号] (仅 Superuser)\n"
                "总结配置 模型 移除 [-g 群号]         (仅 Superuser)\n"
                "总结配置 风格 设置 <风格名称> [-g 群号] (需 Admin)\n"
                "总结配置 风格 移除 [-g 群号]         (需 Admin)\n"
                "总结配置 查看 [-g 群号]\n"
                "注: 不带 -g 时，设置/移除/查看 默认作用于当前群聊。"
            ),
        ),
    ),
    priority=5,
    block=True,
)


from .handlers.group_settings import handle_summary_config
from .handlers.health import (
    handle_health_check as health_check_handler_impl,
)
from .handlers.health import (
    handle_system_repair as system_repair_handler_impl,
)
from .handlers.model_control import (
    handle_key_status,
    handle_list_models,
    handle_switch_model,
    validate_active_model_on_startup,
)
from .handlers.scheduler import (
    check_scheduler_status_handler as check_status_handler_impl,
)
from .handlers.scheduler import (
    handle_summary_remove as summary_remove_handler_impl,
)
from .handlers.scheduler import (
    handle_summary_set as summary_set_handler_impl,
)
from .handlers.summary import handle_summary as summary_handler_impl
from .utils.summary_generation import generate_help_image


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
        if not is_superuser:
            is_ready = summary_cd_limiter.check(user_id_str)
            if not is_ready:
                left = summary_cd_limiter.left_time(user_id_str)
                logger.info(f"用户 {user_id_str} 触发总结命令，但在冷却中 ({left:.1f}s 剩余)")
                await UniMessage.text(f"总结功能冷却中，请等待 {left:.1f} 秒后再试~").send(target)
                return
            else:
                summary_cd_limiter.start_cd(user_id_str)
                logger.debug(f"用户 {user_id_str} (非超级用户) 冷却已启动。")

        await summary_handler_impl(bot, event, result, message_count, style, parts, target)
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
            count_to_validate = least_count_match if least_count_match is not None else default_count
            least_count = validate_msg_count_range(int(count_to_validate))

        except ValueError as e:
            await UniMessage.text(str(e)).send(target)
            return
        except Exception as e:
            logger.error(f"解析时间或数量时出错: {e}", command="定时总结")
            await UniMessage.text(f"解析时间或数量时出错: {e}").send(target)
            return

        await summary_set_handler_impl(bot, event, result, time_tuple, least_count, style_value, target)
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


@summary_check_status.handle()
async def handle_check_status(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, target: MsgTarget):
    await check_status_handler_impl(bot, event, target)


@summary_health.handle()
async def handle_check_health(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, target: MsgTarget):
    await health_check_handler_impl(bot, event, target)


@summary_repair.handle()
async def handle_system_fix(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, target: MsgTarget):
    await system_repair_handler_impl(bot, event, target)


@summary_switch_model.handle()
async def _(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent,
    provider_model: Match[str],
    target: MsgTarget,
):
    if provider_model.available:
        new_name = provider_model.result
        success, message = handle_switch_model(new_name)
        if success:
            Config.set_config("summary_group", "CURRENT_ACTIVE_MODEL_NAME", new_name, True)
            logger.info(f"AI 模型已通过配置持久化切换为: {new_name}")
            await UniMessage.text(f"已成功切换到模型: {new_name}").send(target)
        else:
            await UniMessage.text(message).send(target)
    else:
        await UniMessage.text("请输入要切换的模型名称 (格式: ProviderName/ModelName)。").send(target)


@summary_list_models.handle()
async def _(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, target: MsgTarget):
    current_model_name = base_config.get("CURRENT_ACTIVE_MODEL_NAME")
    message = handle_list_models(current_model_name)
    await UniMessage.text(message).send(target)


@summary_key_status.handle()
async def _(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, target: MsgTarget):
    message = await handle_key_status()
    await UniMessage.text(message).send(target)


@summary_help.handle()
async def _(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, target: MsgTarget):
    try:
        usage_text = __plugin_meta__.usage

        try:
            img_bytes = await generate_help_image(usage_text)
            await UniMessage.image(raw=img_bytes).send(target)
            logger.info("已发送总结帮助图片", command="总结帮助")
        except Exception as e:
            logger.warning(f"生成帮助图片失败，使用文本模式: {e}", command="总结帮助")
            await UniMessage.text(f"📖 群聊总结插件帮助文档\n\n{usage_text}").send(target)
    except Exception as e:
        logger.error(f"总结帮助命令处理失败: {e}", command="总结帮助", e=e)
        await UniMessage.text(f"生成帮助文档时出错: {e}").send(target)


@summary_config_cmd.handle()
async def _(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent,
    target: MsgTarget,
    result: CommandResult,
):
    await handle_summary_config(bot, event, target, result)


@driver.on_startup
async def startup():
    await set_scheduler()
    validate_active_model_on_startup()
    final_active_model = base_config.get("CURRENT_ACTIVE_MODEL_NAME")
    logger.info(f"群聊总结插件启动，当前激活模型: {final_active_model or '未指定或配置错误'}")
