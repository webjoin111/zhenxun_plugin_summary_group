from typing import Any

from nonebot.adapters import Bot

from zhenxun.configs.config import Config
from zhenxun.services.log import logger
from zhenxun.utils.platform import PlatformUtils

# --- 直接获取基础配置 ---
base_config = Config.get("summary_group")

from .health import with_retry
from .scheduler import SummaryException


class MessageFetchException(SummaryException):
    pass


class MessageProcessException(SummaryException):
    pass


async def get_raw_group_msg_history(bot: Bot, group_id: int | str, count: int) -> list:
    try:

        async def fetch():
            response = await bot.get_group_msg_history(group_id=group_id, count=count)
            raw_messages = response.get("messages", response.get("ret", []))
            logger.debug(
                f"从群 {group_id} 获取了 {len(raw_messages)} 条原始消息",
                "get_raw_group_msg_history",
                group_id=group_id,
            )
            return raw_messages

        max_retries = base_config.get("MAX_RETRIES", 2)
        retry_delay = base_config.get("RETRY_DELAY", 1)
        return await with_retry(
            fetch,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )
    except Exception as e:
        logger.error(
            f"获取群 {group_id} 的原始消息历史失败 (with_retry后): {e}",
            "get_raw_group_msg_history",
            group_id=group_id,
            e=e,
        )

        raise MessageFetchException(f"获取原始消息历史失败: {e!s}")


async def process_message(
    messages: list, bot: Bot, group_id: int | str
) -> tuple[list[dict[str, str]], dict[str, str]]:
    logger.debug(
        f"开始处理群 {group_id} 的 {len(messages)} 条原始消息",
        "消息处理",
    )
    try:
        if not messages:
            return [], {}

        # 获取是否排除Bot消息的配置
        exclude_bot = base_config.get("EXCLUDE_BOT_MESSAGES", False)
        bot_self_id = bot.self_id

        user_info_cache: dict[str, str] = {}
        user_ids_to_fetch = {
            str(msg.get("user_id")) for msg in messages if msg.get("user_id")
        }

        for user_id_str in user_ids_to_fetch:
            if user_id_str not in user_info_cache:
                sender_name = f"用户_{user_id_str[-4:]}"
                try:
                    user_data = await PlatformUtils.get_user(
                        bot, user_id_str, str(group_id)
                    )
                    if user_data:
                        sender_name = user_data.card or user_data.name or sender_name
                    user_info_cache[user_id_str] = sender_name
                except Exception as e:
                    logger.warning(
                        f"获取用户 {user_id_str} 信息失败: {e}. 使用默认值",
                        group_id=group_id,
                        e=e,
                    )
                    user_info_cache[user_id_str] = user_info_cache.get(
                        user_id_str, f"用户_{user_id_str[-4:]}"
                    )

        processed_log: list[dict[str, str]] = []
        for msg in messages:
            user_id = msg.get("user_id")
            if not user_id:
                continue

            # 排除Bot自身消息
            user_id_str = str(user_id)
            if exclude_bot and user_id_str == bot_self_id:
                logger.debug(
                    f"排除Bot({bot_self_id})消息", "消息处理", group_id=group_id
                )
                continue

            sender_name = user_info_cache.get(user_id_str, f"用户_{user_id_str[-4:]}")

            raw_segments = msg.get("message", [])
            text_segments: list[str] = []

            for segment in raw_segments:
                if not isinstance(segment, dict):
                    continue
                seg_type = segment.get("type")
                seg_data = segment.get("data", segment)
                if seg_type == "text" and "text" in seg_data:
                    if text := seg_data["text"].strip():
                        text_segments.append(text)
                elif seg_type == "at" and "qq" in seg_data:
                    qq = str(seg_data["qq"])
                    at_name = user_info_cache.get(qq)
                    if not at_name:
                        try:
                            at_user_data = await PlatformUtils.get_user(
                                bot, qq, str(group_id)
                            )
                            if at_user_data:
                                at_name = (
                                    at_user_data.card
                                    or at_user_data.name
                                    or f"用户_{qq[-4:]}"
                                )
                                user_info_cache[qq] = at_name
                            else:
                                at_name = f"用户_{qq[-4:]}"
                        except Exception:
                            at_name = f"用户_{qq[-4:]}"
                    text_segments.append(f"@{at_name}")

            if text_segments:
                message_content = "".join(text_segments)
                processed_log.append({"name": sender_name, "content": message_content})

        logger.debug(
            f"消息处理完成，生成 {len(processed_log)} 条处理记录 (已应用Bot排除设置: {exclude_bot})",
            group_id=group_id,
        )
        return processed_log, user_info_cache

    except Exception as e:
        logger.error(
            f"处理群 {group_id} 消息时出错: {e}",
            "消息处理",
            e=e,
            group_id=group_id,
        )
        raise MessageProcessException(f"消息处理失败: {e!s}")


async def check_message_count(
    messages: list[dict[str, Any]], min_count: int | None = None
) -> bool:
    try:
        if not messages:
            return False

        if min_count is None:
            # --- 使用 base_config.get ---
            min_len = base_config.get("SUMMARY_MIN_LENGTH")
            max_len = base_config.get("SUMMARY_MAX_LENGTH")

            if min_len is None or max_len is None:
                logger.warning(
                    "无法从配置获取 SUMMARY_MIN/MAX_LENGTH，使用默认检查值 (50)"
                )
                min_count = 50
            else:
                try:
                    min_count = min(int(min_len), int(max_len))
                except (ValueError, TypeError):
                    logger.warning(
                        "配置 SUMMARY_MIN/MAX_LENGTH 值无效，使用默认检查值 (50)"
                    )
                    min_count = 50

        return len(messages) >= min_count
    except Exception as e:
        logger.error(f"检查消息数量时出错: {e}", "check_message_count", e=e)
        return False


def check_cooldown(user_id: int | str) -> bool:
    from .. import summary_cd_limiter

    try:
        user_id_str = str(user_id)
        is_ready = summary_cd_limiter.check(user_id_str)
        if not is_ready:
            left = summary_cd_limiter.left_time(user_id_str)
            logger.debug(
                f"用户 {user_id_str} 冷却检查：否 (剩余 {left:.1f}s)",
                "check_cooldown",
            )

        return is_ready
    except Exception as e:
        logger.error(f"检查冷却时间时出错: {e}", "check_cooldown", session=user_id, e=e)

        return True
