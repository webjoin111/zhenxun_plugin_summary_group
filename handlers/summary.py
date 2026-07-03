from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, PrivateMessageEvent
from nonebot.permission import SUPERUSER
from nonebot_plugin_alconna import At, CommandResult, Match, Text
from nonebot_plugin_alconna.uniseg import Target, UniMessage

from zhenxun.services.log import logger

from ..config import GroupSettings
from ..services import SummaryParameters, SummaryService
from ..utils import SummaryException


async def handle_summary(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent,
    result: CommandResult,
    message_count: int | str,
    style: Match[str],
    parts: Match[list[At | Text]],
    target: Target,
    group_config: GroupSettings,
):
    """
    处理核心的“总结”命令。

    负责解析所有参数、验证权限、准备数据，并调用 SummaryService 来执行总结任务。
    """
    user_id_str = event.get_user_id()
    originating_group_id = (
        event.group_id if isinstance(event, GroupMessageEvent) else None
    )
    is_superuser = await SUPERUSER(bot, event)

    try:
        from .. import validate_msg_count_range

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

    arp = result.result
    target_group_id_match = arp.query("g.target_group_id") if arp else None

    if target_group_id_match and is_superuser:
        target_group_id_to_fetch = int(target_group_id_match)
    else:
        target_group_id_to_fetch = originating_group_id

    if target_group_id_match and not is_superuser:
        await UniMessage.text("需要超级用户权限才能使用 -g 参数指定群聊。").send(target)
        logger.warning(f"用户 {user_id_str} (非超级用户) 尝试使用 -g 参数")
        return

    if target_group_id_to_fetch is None:
        await UniMessage.text(
            "请在群聊中使用此命令，或使用 -g <群号> 参数指定目标群聊。 (仅限超级用户)"
        ).send(target)
        return

    target_user_ids: set[str] = set()
    content_parts: list[str] = []

    all_extra_args = []
    if parts.available:
        all_extra_args.extend(parts.result)
    if arp and "$extra" in arp.main_args:
        all_extra_args.extend(arp.main_args["$extra"])

    for part in all_extra_args:
        if isinstance(part, At) and part.target:
            target_user_ids.add(str(part.target))
        elif isinstance(part, Text):
            stripped_text = part.text.strip()
            if stripped_text:
                content_parts.append(stripped_text)

    content_value = " ".join(content_parts)

    logger.debug(
        f"总结参数: 目标群={target_group_id_to_fetch}, 消息数量={message_count}, "
        f"风格={style.result if style.available else '默认'}, "
        f"用户过滤={target_user_ids}, 内容过滤='{content_value}'",
        command="总结",
    )

    feedback_target_group_part = (
        f"群聊 {target_group_id_to_fetch} 的"
        if (target_group_id_match and is_superuser)
        else "群聊"
    )
    feedback = f"正在生成{feedback_target_group_part}总结"
    if style.available:
        feedback += f"（风格: {style.result}）"
    feedback += f"{'（指定用户）' if target_user_ids else ''}{'（关键词过滤）' if content_value else ''}，请稍候..."  # noqa: E501
    await UniMessage.text(feedback).send(target)

    try:
        params = SummaryParameters(
            bot=bot,
            target_group_id=target_group_id_to_fetch,
            message_count=message_count,
            style=style.result if style.available else None,
            content_filter=content_value,
            target_user_ids=target_user_ids,
            response_target=target,
            group_config=group_config,
        )

        service = SummaryService(params)
        await service.execute()

    except SummaryException:
        return
    except Exception as e:
        logger.error(
            f"处理总结命令时发生未知异常: {e}",
            command="总结",
            session=event.get_user_id(),
            group_id=getattr(event, "group_id", None),
        )
        try:
            await UniMessage.text("处理命令时发生内部错误，请联系管理员。").send(target)
        except Exception:
            logger.error("发送最终错误消息失败", command="总结")
