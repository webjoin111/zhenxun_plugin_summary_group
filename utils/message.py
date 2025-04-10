from typing import List, Dict, Union, Optional, Any, Tuple, Set
from datetime import datetime, timedelta
from collections import defaultdict
from zhenxun.services.log import logger
from nonebot.adapters.onebot.v11 import Bot
import time


from zhenxun.configs.config import Config


from .scheduler import SummaryException
from .health import with_retry


class MessageFetchException(SummaryException):
    pass


def validate_message_count(num: int) -> bool:

    base_config = Config.get("summary_group")
    min_len = base_config.get("SUMMARY_MIN_LENGTH")
    max_len = base_config.get("SUMMARY_MAX_LENGTH")

    return min_len <= num <= max_len


async def get_group_msg_history(
    bot: Bot, group_id: int, count: int, target_user_ids: Set[str] | None = None
) -> Tuple[List[Dict[str, str]], Dict[str, str]]:
    from .summary import process_message

    async def fetch_messages():
        try:

            response = await bot.get_group_msg_history(group_id=group_id, count=count)
            raw_messages = response.get("messages", [])

            logger.debug(
                f"从群 {group_id} 获取了 {len(raw_messages)} 条原始消息",
                command="get_group_msg_history",
                group_id=group_id,
            )

            filtered_messages = raw_messages
            if target_user_ids:
                filtered_messages = [
                    msg
                    for msg in raw_messages
                    if str(msg.get("user_id")) in target_user_ids
                ]
                logger.debug(
                    f"过滤后剩余 {len(filtered_messages)} 条消息 (来自用户: {target_user_ids})",
                    command="get_group_msg_history",
                    group_id=group_id,
                )

            if not filtered_messages:
                logger.warning(
                    f"群 {group_id} 未返回任何有效消息{'（指定用户）' if target_user_ids else ''}",
                    command="get_group_msg_history",
                    group_id=group_id,
                )
                return [], {}

            processed_data, user_info_cache = await process_message(
                filtered_messages, bot, group_id
            )
            return processed_data, user_info_cache
        except MessageFetchException:
            raise
        except Exception as e:
            logger.error(
                f"获取或处理群 {group_id} 的消息历史失败: {e}",
                command="get_group_msg_history",
                group_id=group_id,
                e=e,
            )
            raise MessageFetchException(f"获取或处理消息历史失败: {str(e)}")

    try:

        return await with_retry(
            fetch_messages,
            max_retries=Config.get("summary_group").get("MAX_RETRIES", 2),
            retry_delay=Config.get("summary_group").get("RETRY_DELAY", 1),
        )
    except MessageFetchException:
        raise
    except Exception as e:
        logger.error(
            f"消息获取过程中出现意外错误: {e}",
            command="get_group_msg_history",
            group_id=group_id,
            e=e,
        )
        raise MessageFetchException(f"获取消息失败: {str(e)}")


async def check_message_count(
    messages: List[Dict[str, Any]], min_count: Optional[int] = None
) -> bool:
    try:
        if not messages:
            return False

        if min_count is None:
            base_config = Config.get("summary_group")
            min_len = base_config.get("SUMMARY_MIN_LENGTH")
            max_len = base_config.get("SUMMARY_MAX_LENGTH")
            min_count = min(min_len, max_len)

        return len(messages) >= min_count
    except Exception as e:
        logger.error(f"检查消息数量时出错: {e}", command="check_message_count", e=e)
        return False


def check_cooldown(user_id: int) -> bool:
    try:
        base_config = Config.get("summary_group")
        cooldown_setting = base_config.get("SUMMARY_COOL_DOWN")
        if not cooldown_setting:
            return True

        from ..store import Store

        store = Store()
        last_time = store.get_cooldown(user_id)

        if not last_time:
            return True

        now = time.time()
        if now - last_time >= cooldown_setting:
            return True

        return False
    except Exception as e:
        logger.error(
            f"检查冷却时间时出错: {e}", command="check_cooldown", session=user_id, e=e
        )
        return True
