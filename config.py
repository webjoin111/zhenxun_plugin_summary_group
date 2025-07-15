from zhenxun.configs.config import Config

base_config = Config.get("summary_group")


class SummaryConfig:
    """群聊总结插件配置类"""

    USER_INFO_TIMEOUT = 10
    USER_INFO_BATCH_SIZE = 10

    AVATAR_CACHE_SIZE = 100
    AVATAR_MAX_COUNT = 50
    AVATAR_CACHE_EXPIRE_DAYS = 7

    MESSAGE_PROCESS_TIMEOUT = 60
    CONCURRENT_USER_FETCH_LIMIT = 3

    USER_INFO_MAX_RETRIES = 2
    USER_INFO_RETRY_DELAY = 1.0

    TIME_OUT = 120
    MAX_RETRIES = 3
    RETRY_DELAY = 2
    CONCURRENT_TASKS = 2

    @classmethod
    def get_user_info_timeout(cls) -> int:
        """获取用户信息超时时间"""
        return getattr(cls, "USER_INFO_TIMEOUT", 5)

    @classmethod
    def get_user_info_batch_size(cls) -> int:
        """获取用户信息批次大小"""
        return getattr(cls, "USER_INFO_BATCH_SIZE", 10)

    @classmethod
    def get_message_process_timeout(cls) -> int:
        """获取消息处理超时时间"""
        return getattr(cls, "MESSAGE_PROCESS_TIMEOUT", 30)

    @classmethod
    def get_concurrent_user_fetch_limit(cls) -> int:
        """获取并发用户信息获取限制"""
        return getattr(cls, "CONCURRENT_USER_FETCH_LIMIT", 5)

    @classmethod
    def get_user_info_max_retries(cls) -> int:
        """获取用户信息最大重试次数"""
        return getattr(cls, "USER_INFO_MAX_RETRIES", 1)

    @classmethod
    def get_user_info_retry_delay(cls) -> float:
        """获取用户信息重试延迟"""
        return getattr(cls, "USER_INFO_RETRY_DELAY", 0.5)

    @classmethod
    def get_avatar_cache_size(cls) -> int:
        """获取头像缓存大小"""
        return getattr(cls, "AVATAR_CACHE_SIZE", 100)

    @classmethod
    def get_avatar_max_count(cls) -> int:
        """获取单次处理的最大头像数量"""
        return getattr(cls, "AVATAR_MAX_COUNT", 15)

    @classmethod
    def get_avatar_cache_expire_days(cls) -> int:
        """获取头像缓存过期时间（天）"""
        return getattr(cls, "AVATAR_CACHE_EXPIRE_DAYS", 7)

    @classmethod
    def get_timeout(cls) -> int:
        """获取API请求超时时间"""
        return getattr(cls, "TIME_OUT", 120)

    @classmethod
    def get_max_retries(cls) -> int:
        """获取API请求最大重试次数"""
        return getattr(cls, "MAX_RETRIES", 3)

    @classmethod
    def get_retry_delay(cls) -> int:
        """获取API请求重试延迟时间"""
        return getattr(cls, "RETRY_DELAY", 2)

    @classmethod
    def get_concurrent_tasks(cls) -> int:
        """获取同时处理总结任务的最大数量"""
        return getattr(cls, "CONCURRENT_TASKS", 2)


summary_config = SummaryConfig()
