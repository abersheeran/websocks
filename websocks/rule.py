import os
import base64
import typing
import logging
from urllib import request

from .utils import Singleton

root = os.path.dirname(os.path.abspath(__file__))

if not os.path.exists(root):
    os.makedirs(root)

gfwlist_path = os.path.join(root, "gfwlist.txt")
whitelist_path = os.path.join(root, "whitelist.txt")

cache: typing.Set[str] = set()
logger = logging.getLogger(__name__)


class FilterRule(metaclass=Singleton):
    def __init__(self, yourself_s: typing.Sequence[str] = []) -> None:
        self.yourself_s = list(yourself_s)

    @staticmethod
    def download_gfwlist(
        url: str = "https://cdn.jsdelivr.net/gh/gfwlist/gfwlist/gfwlist.txt",
    ) -> None:
        if url is None:
            print("gfwlist url is None, nothing to do.", flush=True)
            return
        req = request.Request(url, method="GET")
        resp = request.urlopen(req)
        with open(gfwlist_path, "wb+") as file:
            base64.decode(resp, file)

    @staticmethod
    def download_whitelist(
        url: str = "https://cdn.jsdelivr.net/gh/abersheeran/websocks/websocks/whitelist.txt",
    ) -> None:
        if url is None:
            print("whitelist url is None, nothing to do.", flush=True)
            return
        req = request.Request(url, method="GET")
        resp = request.urlopen(req)
        with open(whitelist_path, "wb+") as file:
            file.write(resp.read())

    @staticmethod
    def open(filepath: str) -> typing.Generator:
        try:
            with open(filepath, "r") as file:
                for line in file.readlines():
                    yield line.strip()
        except FileNotFoundError:
            pass

    def judge(self, host: str) -> typing.Optional[bool]:
        """
        匹配例外则返回 False, 匹配成功则返回 True.
        不在规则内返回 None.
        """
        result = self._judge_yourself(host)
        if result is not None:
            return result
        result = self._judge_whitelist(host)
        if result is not None:
            return result
        result = self._judge_gfwlist(host)
        if result is not None:
            return result

    def _judge_whitelist(self, host: str) -> typing.Optional[bool]:
        """
        从白名单中匹配
        """
        return self._judge_from_file(whitelist_path, host)

    def _judge_gfwlist(self, host: str) -> typing.Optional[bool]:
        """
        从 GFWList 中匹配
        """
        return self._judge_from_file(gfwlist_path, host)

    def _judge_yourself(self, host: str) -> typing.Optional[bool]:
        """
        从自定义文件中匹配
        """
        for filepath in self.yourself_s:
            result = self._judge_from_file(filepath, host)
            if result is not None:
                return result

    def _judge_from_file(self, filepath: str, host: str) -> typing.Optional[bool]:
        for line in self.open(filepath):
            line = line.strip()
            if not line:
                continue
            result = self._judge(line, host)
            if result is not None:
                return result

    def _judge(self, line: str, host: str) -> typing.Optional[bool]:
        if line.startswith("!"):
            return None
        if line[:2] == "||":
            if host.endswith(line[2:]):
                return True
        elif line[0] == ".":
            if host.endswith(line) or host == line[1:]:
                return True
        elif line.startswith("@@"):
            _ = self._judge(line[2:], host)
            if _ is not None:
                return not _
        else:
            if host.startswith(line):
                return True


def judge(host: str) -> typing.Optional[bool]:
    """检查是否需要走代理"""
    if host in cache:
        return True

    result = FilterRule().judge(host)

    if result is True:
        cache.add(host)
    return result


def add(host: str) -> None:
    """增加新的 host 进加速名单"""
    cache.add(host)
