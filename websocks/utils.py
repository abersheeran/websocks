import asyncio
from asyncio import Task, Future, CancelledError
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


def onlyfirst(*coros, loop=None) -> Awaitable[Any]:
    """
    Execute multiple coroutines concurrently, returning only the results of the first execution.

    When one is completed, the execution of other coroutines will be canceled.
    """
    loop = loop or asyncio.get_running_loop()
    tasks: Set[Task] = set()
    finished, result, _future = 0, loop.create_future(), None

    def _done_callback(fut: Future) -> None:
        nonlocal finished, result, _future

        try:
            fut.result()  # try raise exception
        except CancelledError:
            fut.cancel()
        except Exception as e:
            result.set_exception(e)

        finished += 1

        if _future is None:
            _future = fut

        for task in tasks:
            if task.done() or task.cancelled():
                continue
            task.cancel()

        if finished == len(tasks) and not result.done():
            result.set_result(_future.result())

    for coro in coros:
        task = loop.create_task(coro)
        task.add_done_callback(_done_callback)
        tasks.add(task)

    return result
