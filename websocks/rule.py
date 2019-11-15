import os
import re
import base64
import typing
from urllib import request

IPV4_PATTERN = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}")

# if os.name == "posix":
#     root = "~"
# else:
#     root = os.environ.get("USERPROFILE", "C:")
#
# root = os.path.join(root, '.websocks')

root = os.path.dirname(os.path.abspath(__file__))

if not os.path.exists(root):
    os.makedirs(root)

gfwlist_path = os.path.join(
    root,
    'gfwlist.txt'
)
whitelist_path = os.path.join(
    root,
    'whitelist.txt'
)

cache: set = set()


def is_ipv4(host: str) -> bool:
    """判断 host 是否为 IPV4 地址"""
    return IPV4_PATTERN.match(host) is not None


def is_local_ipv4(host: str) -> bool:
    if host.startswith("10.") or host.startswith("127."):
        # A类地址
        return True
    if host.startswith("169.254.") or \
            (host.startswith("172.") and 16 <= int(host.split(".")[1]) <= 31):
        # B类地址
        return True
    if host.startswith("192.168."):
        # C类地址
        return True
    return False


class FilterRule:

    def __init__(self) -> None:
        self.GOOGLE = re.compile(r".*?google\.[A-Za-z0-9-]+")
        self.BLOGSPOT = re.compile(r".*?blogspot\.[A-Za-z0-9-]+")

    @staticmethod
    def download_gfwlist(url: str = "https://raw.githubusercontent.com/gfwlist/gfwlist/master/gfwlist.txt") -> None:
        if url is None:
            print("gfwlist url is None, nothing to do.", flush=True)
            return
        req = request.Request(url, method="GET")
        resp = request.urlopen(req)
        with open(gfwlist_path, 'wb+') as file:
            base64.decode(resp, file)

    @staticmethod
    def download_whitelist(url: str = "https://raw.githubusercontent.com/abersheeran/websocks/master/websocks/whitelist.txt") -> None:
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
            file = open(filepath, "r")
            for line in file.readlines():
                yield line
        except FileNotFoundError:
            pass

    def judge(self, host: str) -> typing.Optional[bool]:
        """
        匹配例外则返回 False, 匹配成功则返回 True.
        不在规则内返回 None.
        """
        result = None
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
        for line in self.open(whitelist_path):
            line = line.strip()
            if not line:
                continue
            result = self._judge(line, host)
            if result is not None:
                return result

    def _judge_gfwlist(self, host: str) -> typing.Optional[bool]:
        """
        从 GFWList 中匹配
        """
        for line in self.open(gfwlist_path):
            line = line.strip()
            if not line:
                continue
            result = self._judge(line, host)
            if result is not None:
                return result
        if self.GOOGLE.match(host):
            return True
        if self.BLOGSPOT.match(host):
            return True

    def _judge(self, line: str, host: str) -> typing.Optional[bool]:
        if line.startswith("!"):
            return None
        if line[:2] == "||":
            if host.startswith(line[2:]):
                return True
        elif line[0] == ".":
            if host.endswith(line):
                return True
        elif line.startswith("@@"):
            _ = self._judge(line[2:], host)
            if _ is not None:
                return not _
        else:
            if host.startswith(line):
                return True


hostlist = FilterRule()


def judge(host: str) -> typing.Optional[bool]:
    """检查是否需要走代理"""
    if is_ipv4(host):
        return not is_local_ipv4(host)

    if host in cache:
        return True

    result = hostlist.judge(host)
    if result is True:
        cache.add(host)
    return result


def add(host: str) -> None:
    """增加新的 host 进加速名单"""
    cache.add(host)


if __name__ == "__main__":
    hostlist.download_gfwlist()
    hostlist.download_whitelist()
