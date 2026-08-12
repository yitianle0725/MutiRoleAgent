"""
重试 + 熔断器
=============
为 yuc.wiki / bangumi.lol 等外部爬虫提供统一的容错机制。

特性
----
- **指数退避重试**：1s → 2s → 4s → ... 最多 30s
- **熔断器**：连续失败 3 次后，冷却 5 分钟，期间拒绝请求直接 fallback
- **半开状态**：冷却期满后允许一次试探请求，成功则恢复，失败继续冷却

使用方式::

    from anime.retry_handler import retry_with_backoff, circuit_breaker

    @retry_with_backoff(max_retries=3)
    def my_crawler():
        return requests.get(...)

    if not circuit_breaker("yuc").is_available():
        return fallback_to_local_kb()
"""

import time
import functools
import threading
from dataclasses import dataclass, field


# ==================== 熔断器 ====================

@dataclass
class _CircuitState:
    """单个服务的熔断状态。"""
    name: str
    max_failures: int = 3
    cooldown_seconds: float = 300.0  # 5 分钟
    failure_count: int = 0
    last_failure_time: float = 0.0


class CircuitBreakerManager:
    """全局熔断器管理器，每服务一个实例。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._circuits: dict[str, _CircuitState] = {}

    def get(self, name: str) -> _CircuitState:
        with self._lock:
            if name not in self._circuits:
                self._circuits[name] = _CircuitState(name=name)
            return self._circuits[name]

    def is_available(self, name: str) -> bool:
        """服务是否可调用。"""
        c = self.get(name)
        if c.failure_count < c.max_failures:
            return True
        # 检查冷却期是否结束
        elapsed = time.time() - c.last_failure_time
        if elapsed > c.cooldown_seconds:
            # 半开：允许一次试探
            c.failure_count = c.max_failures - 1
            return True
        return False

    def record_success(self, name: str):
        c = self.get(name)
        c.failure_count = 0
        c.last_failure_time = 0.0

    def record_failure(self, name: str):
        c = self.get(name)
        c.failure_count += 1
        c.last_failure_time = time.time()

    def status(self, name: str) -> str:
        c = self.get(name)
        if c.failure_count >= c.max_failures:
            elapsed = time.time() - c.last_failure_time
            remaining = max(0, c.cooldown_seconds - elapsed)
            return f"OPEN (冷却中, 剩余 {remaining:.0f}s)"
        return f"CLOSED (failures={c.failure_count}/{c.max_failures})"


# 全局单例
_circuit_manager = CircuitBreakerManager()


def circuit_breaker(name: str):
    """获取指定服务的熔断器便捷入口。

    Returns:
        CircuitBreakerManager 实例（可调用 is_available / record_success / record_failure）
    """
    # 返回小代理对象方便调用
    class _Proxy:
        @staticmethod
        def is_available(): return _circuit_manager.is_available(name)
        @staticmethod
        def record_success(): _circuit_manager.record_success(name)
        @staticmethod
        def record_failure(): _circuit_manager.record_failure(name)
        @staticmethod
        def status(): return _circuit_manager.status(name)
    return _Proxy()


# ==================== 指数退避重试 ====================

def retry_with_backoff(max_retries: int = 3, base_delay: float = 1.0,
                       max_delay: float = 30.0, retryable_exceptions: tuple = (Exception,)):
    """指数退避重试装饰器。

    Args:
        max_retries: 最大重试次数（不含首次调用）
        base_delay: 基础延迟秒数，每次翻倍
        max_delay: 延迟上限
        retryable_exceptions: 可重试的异常类型
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        print(f"[retry] {func.__name__} 第 {attempt + 1}/{max_retries} 次重试, "
                              f"等待 {delay:.1f}s: {e}")
                        time.sleep(delay)
                    else:
                        print(f"[retry] {func.__name__} 重试 {max_retries} 次后仍失败: {e}")
            raise last_exception
        return wrapper
    return decorator


# ==================== 组合使用 ====================

def call_with_circuit_breaker(service_name: str, func, *args,
                               fallback=None, **kwargs):
    """带熔断保护的函数调用。

    1. 检查熔断器状态，OPEN 则走 fallback
    2. 执行函数，成功则记录、失败则记录并走 fallback

    Args:
        service_name: 服务名（yuc / bangumi）
        func:         要调用的函数
        *args, **kwargs: 函数参数
        fallback:     熔断/失败时的回调，接收异常参数

    Returns:
        函数返回值或 fallback 返回值
    """
    cb = circuit_breaker(service_name)
    if not cb.is_available():
        print(f"[circuit] {service_name} 熔断器 OPEN，走 fallback")
        if fallback:
            return fallback(RuntimeError(f"{service_name} 服务暂不可用（熔断中）"))
        return None

    try:
        result = func(*args, **kwargs)
        cb.record_success()
        return result
    except Exception as e:
        cb.record_failure()
        print(f"[circuit] {service_name} 调用失败: {e}，状态={cb.status()}")
        if fallback:
            return fallback(e)
        return None
