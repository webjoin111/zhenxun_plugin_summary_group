# utils/__init__.py
# 消息处理功能
from .message import (
    get_group_msg_history,
    MessageFetchException,
    check_cooldown,
    get_raw_group_msg_history,
    MessageProcessException,
)

# 总结功能
from .summary import (
    messages_summary,
    process_message,
    generate_image,
    send_summary,
    ModelException,
    ImageGenerationException,
)

# 定时任务和队列管理
from .scheduler import (
    set_scheduler,
    update_single_group_schedule,
    scheduler_send_summary,
    process_summary_queue,
    check_scheduler_status,
    verify_processor_status,
    SummaryException,
    ScheduleException,
    task_processor_started,
)

# 系统健康状态
from .health import (
    check_system_health,
    with_retry,
)

__all__ = [
    # 异常类
    "SummaryException",
    "ModelException",
    "MessageFetchException",
    "ScheduleException",
    "MessageProcessException",
    "ImageGenerationException",
    # 消息处理
    "get_group_msg_history",
    "get_raw_group_msg_history",
    "check_cooldown",
    # 总结功能
    "messages_summary",
    "process_message",
    "generate_image",
    "send_summary",
    # 定时任务和队列
    "set_scheduler",
    "update_single_group_schedule",
    "scheduler_send_summary",
    "process_summary_queue",
    "check_scheduler_status",
    "verify_processor_status",
    "task_processor_started",
    # 系统健康
    "check_system_health",
    "with_retry",
]
