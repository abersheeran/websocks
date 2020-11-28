import asyncio
import os
import threading
import winreg
from asyncio import AbstractEventLoop, Task, Future
from dataclasses import dataclass
from enum import Enum
from typing import Tuple, List, Dict, Any, Set, Optional, Coroutine


class Singleton(type):
    def __init__(
        cls, name: str, bases: Tuple[type], namespace: Dict[str, Any],
    ) -> None:
        cls.instance = None
        super().__init__(name, bases, namespace)

    def __call__(cls, *args, **kwargs) -> Any:
        if cls.instance is None:
            cls.instance = super().__call__(*args, **kwargs)
        return cls.instance


def onlyfirst(*coros: Coroutine, loop: Optional[AbstractEventLoop] = None) -> Future:
    """
    Execute multiple coroutines concurrently, returning only the results of the first execution.

    When one is completed, the execution of other coroutines will be canceled.
    """
    loop = loop or asyncio.get_running_loop()
    tasks: Set[Task] = set()
    result, _future = loop.create_future(), None

    def _done_callback(fut: Future) -> None:
        nonlocal result, _future

        if result.cancelled():
            return  # nothing to do on onlyfirst cancelled

        if _future is None:
            _future = fut  # record first completed future

        cancel_all_task()

        if not result.done():
            if _future.exception() is None:
                result.set_result(_future.result())
            else:
                result.set_exception(_future.exception())

    def cancel_all_task() -> None:
        for task in tasks:
            task.remove_done_callback(_done_callback)

        for task in filter(lambda task: not task.done(), tasks):
            task.cancel()

    for coro in coros:
        task: Task = loop.create_task(coro)
        task.add_done_callback(_done_callback)
        tasks.add(task)

    result.add_done_callback(lambda fut: cancel_all_task())

    return result


class RestartPolicy(int, Enum):
    NONE = 0
    FAILURE = -1
    ALWAYS = 1


def create_task(
    loop: AbstractEventLoop, coroutine: Coroutine, *, restart_on=RestartPolicy.ALWAYS
) -> None:
    """

    """
    task = loop.create_task(coroutine)

    if restart_on == RestartPolicy.FAILURE:

        def callback(fut: Future):
            if fut.cancelled():
                return
            if fut.exception() is not None:
                create_task(loop, coroutine, __task__=task, restart_on=restart_on)

        task.add_done_callback(callback)

    elif restart_on == RestartPolicy.ALWAYS:

        def callback(fut: Future):
            create_task(loop, coroutine, __task__=task, restart_on=restart_on)

        task.add_done_callback(callback)


class State(dict):
    """
    An object that can be used to store arbitrary state.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.sync_lock = threading.Lock()
        self.async_lock = asyncio.Lock()

    def __enter__(self):
        self.sync_lock.acquire()
        return self

    def __exit__(self, exc_type, value, traceback):
        self.sync_lock.release()

    async def __aenter__(self):
        await self.async_lock.acquire()
        return self

    async def __aexit__(self, exc_type, value, traceback):
        self.async_lock.release()

    def __setattr__(self, name: Any, value: Any) -> None:
        self[name] = value

    def __getattr__(self, name: Any) -> Any:
        try:
            return self[name]
        except KeyError:
            message = "'{}' object has no attribute '{}'"
            raise AttributeError(message.format(self.__class__.__name__, name))

    def __delattr__(self, name: Any) -> None:
        del self[name]


def set_proxy(
    enable: bool,
    proxy: str,
    ignores: List[str] = [
        "localhost",
        "127.*",
        "10.*",
        "172.16.*",
        "172.17.*",
        "172.18.*",
        "172.19.*",
        "172.20.*",
        "172.21.*",
        "172.22.*",
        "172.23.*",
        "172.24.*",
        "172.25.*",
        "172.26.*",
        "172.27.*",
        "172.28.*",
        "172.29.*",
        "172.30.*",
        "172.31.*",
        "172.32.*",
        "192.168.*",
    ],
):
    """
    设定系统的网络代理
    """
    if os.name == "nt":
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            "Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings",
            0,
            winreg.KEY_WRITE,
        )
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, int(enable))
        winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, proxy)
        winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, ";".join(ignores))
