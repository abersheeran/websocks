import asyncio
import threading
from asyncio import Task, Future
from typing import Tuple, Dict, Any, Set, Optional


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


def onlyfirst(*coros, loop=None) -> Future:
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
