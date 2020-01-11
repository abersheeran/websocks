import logging
from typing import Set, Tuple, Dict, Any
from asyncio import Future, Task, CancelledError

logger: logging.Logger = logging.getLogger("websocks")


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


def onlyfirst(*coros, loop=None):
    """
    并发执行多个 coroutine, 仅返回第一个执行完成的结果

    当有一个完成时, 将取消其他 coroutine 的执行
    """
    loop = loop or asyncio.get_running_loop()
    tasks: Set[Task] = set()
    finished, result, _future = 0, loop.create_future(), None

    def _done_callback(fut: Future) -> None:
        try:
            fut.result()  # try raise exception
        except CancelledError:
            fut.cancel()

        nonlocal finished, result, _future

        finished += 1

        if _future is None:
            _future = fut

        for task in tasks:
            if task.done() or task.cancelled():
                continue
            task.cancel()

        if finished == len(tasks):
            result.set_result(_future.result())

    for coro in coros:
        task = loop.create_task(coro)
        task.add_done_callback(_done_callback)
        tasks.add(task)

    return result
