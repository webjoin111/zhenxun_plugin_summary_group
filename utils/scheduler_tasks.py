from nonebot.adapters.onebot.v11 import Bot
from pydantic import BaseModel, Field

from zhenxun.services import (
    ScheduleContext,
    group_settings_service,
    scheduler_manager,
)
from zhenxun.services.ai.core.exceptions import LLMException
from zhenxun.services.log import logger

from .. import base_config
from ..commands import summary_group
from ..config import GroupSettings
from .core import SummaryException


class SummaryTaskParams(BaseModel):
    """定时总结任务的参数模型"""

    message_count: int | str = Field(
        default_factory=lambda: base_config.get("SUMMARY_MAX_LENGTH", 1000),
        description="总结的消息数量或关键字'当天'",
    )
    style: str | None = Field(default=None, description="总结的风格")
    model: str | None = Field(default=None, description="使用的AI模型")


@scheduler_manager.register(
    "summary_group",
    params_model=SummaryTaskParams,
    cli_parser=summary_group.command(),
    default_interval=150,
)
async def scheduled_summary_job(
    bot: Bot,
    context: ScheduleContext,
    params: SummaryTaskParams,
) -> None:
    """
    这是由 scheduler_manager 调度的、支持依赖注入的任务函数。
    它处理单个群组的总结任务。
    - `bot`: 由调度器自动注入的Bot实例。
    - `context`: 包含任务元数据（如ID、目标群组）的上下文。
    - `params`: 经过Pydantic验证的任务参数。
    """
    group_id = context.group_id
    if not group_id:
        logger.warning(
            f"定时总结任务 (ID: {context.schedule_id}) 缺少 group_id，跳过执行。"
        )
        return

    task_id = f"summary_task_{group_id}"
    logger.info(f"开始执行定时总结任务 [{task_id}]", group_id=group_id)

    try:
        message_count = params.message_count
        style = params.style
        model = params.model

        from .message_processing import get_group_messages
        from .summary_generation import messages_summary, send_summary

        group_config = await group_settings_service.get_all_for_plugin(
            group_id, "summary_group", parse_model=GroupSettings
        )

        min_len_required = base_config.get("SUMMARY_MIN_LENGTH", 50)
        if isinstance(message_count, int) and message_count < min_len_required:
            logger.warning(
                f"[{task_id}] 群 {group_id} 定时任务的消息数 ({message_count}) "
                f"低于系统要求 ({min_len_required})，跳过本次执行。"
            )
            return

        processed_messages, user_info_cache = await get_group_messages(
            bot,
            int(group_id),
            message_count,
            use_db=base_config.get("USE_DB_HISTORY", False),
        )

        if not processed_messages or len(processed_messages) < min_len_required:
            logger.info(
                f"[{task_id}] 群 {group_id} 消息数量不足 "
                f"({len(processed_messages)}/{min_len_required})，不生成总结。"
            )
            return

        from nonebot_plugin_alconna.uniseg import Target

        msg_target = Target.group(group_id=group_id)

        summary = await messages_summary(
            target=msg_target,
            messages=processed_messages,
            style=style,
            model_name=model,
            group_config=group_config,
        )

        await send_summary(bot, msg_target, summary, user_info_cache)

    except (SummaryException, LLMException) as e:
        logger.error(f"[{task_id}] 执行定时总结失败: {e}", group_id=group_id, e=e)
    except Exception as e:
        logger.error(
            f"[{task_id}] 执行定时总结时发生未知错误: {e}", group_id=group_id, e=e
        )
