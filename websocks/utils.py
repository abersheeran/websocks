import asyncio
from asyncio import Task, Future
from typing import Tuple, Dict, Any, Set, Awaitable


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
            try:
                result.set_result(_future.result())
            except Exception:
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
