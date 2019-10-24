import os
import json
import atexit

here = os.path.dirname(os.path.abspath(__file__))

cache: set = set()


def _read() -> None:
    try:
        with open(f"{here}/rule.json") as file:
            data = json.load(file)
            cache.update(data)
    except FileNotFoundError:
        pass


def _write() -> None:
    with open(f"{here}/rule.json", "w") as file:
        json.dump(list(cache), file, indent=4)


def judge(host: str) -> bool:
    """检查是否需要走代理"""
    return host in cache


def add(host: str) -> None:
    """增加新的 host 进加速名单"""
    cache.add(host)


_read()
atexit.register(_write)
