class SummaryException(Exception):
    """总结功能相关的基础异常类"""
    pass


class ScheduleException(SummaryException):
    """调度相关的异常"""
    pass


class ModelException(SummaryException):
    """模型相关的异常"""
    pass


class MessageFetchException(SummaryException):
    """消息获取相关的异常"""
    pass


class MessageProcessException(SummaryException):
    """消息处理相关的异常"""
    pass


class ImageGenerationException(SummaryException):
    """图片生成相关的异常"""
    pass
