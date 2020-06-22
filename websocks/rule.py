import os
import re
import base64
import typing
import ipaddress
from urllib import request

from .utils import Singleton

# if os.name == "posix":
#     root = "~"
# else:
#     root = os.environ.get("USERPROFILE", "C:")
#
# root = os.path.join(root, '.websocks')

root = os.path.dirname(os.path.abspath(__file__))

if not os.path.exists(root):
    os.makedirs(root)

gfwlist_path = os.path.join(root, "gfwlist.txt")
whitelist_path = os.path.join(root, "whitelist.txt")
cn_ip_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cn-ip.txt")


def get_cn_ipv4_network() -> typing.Set[ipaddress.IPv4Network]:
    result = set()
    with open(cn_ip_path) as file:
        for line in file:
            result.add(ipaddress.IPv4Network(line.strip()))
    return result


cache: set = set()


class FilterRule(metaclass=Singleton):
    def __init__(self, yourselfs: typing.Sequence[str] = []) -> None:
        self.black_list = (
            re.compile(
                r".*?google\.(ac|ad|ae|af|al|am|as|at|az|ba|be|bf|bg|bi|bj|bs|bt|by|ca|cat|cd|cf|cg|ch|ci|cl|cm|co.ao|co.bw|co.ck|co.cr|co.id|co.il|co.in|co.jp|co.ke|co.kr|co.ls|co.ma|com|com.af|com.ag|com.ai|com.ar|com.au|com.bd|com.bh|com.bn|com.bo|com.br|com.bz|com.co|com.cu|com.cy|com.do|com.ec|com.eg|com.et|com.fj|com.gh|com.gi|com.gt|com.hk|com.jm|com.kh|com.kw|com.lb|com.ly|com.mm|com.mt|com.mx|com.my|com.na|com.nf|com.ng|com.ni|com.np|com.om|com.pa|com.pe|com.pg|com.ph|com.pk|com.pr|com.py|com.qa|com.sa|com.sb|com.sg|com.sl|com.sv|com.tj|com.tr|com.tw|com.ua|com.uy|com.vc|com.vn|co.mz|co.nz|co.th|co.tz|co.ug|co.uk|co.uz|co.ve|co.vi|co.za|co.zm|co.zw|cv|cz|de|dj|dk|dm|dz|ee|es|eu|fi|fm|fr|ga|ge|gg|gl|gm|gp|gr|gy|hk|hn|hr|ht|hu|ie|im|iq|is|it|it.ao|je|jo|kg|ki|kz|la|li|lk|lt|lu|lv|md|me|mg|mk|ml|mn|ms|mu|mv|mw|mx|ne|nl|no|nr|nu|org|pl|pn|ps|pt|ro|rs|ru|rw|sc|se|sh|si|sk|sm|sn|so|sr|st|td|tg|tk|tl|tm|tn|to|tt|us|vg|vn|vu|ws)"
            ),
            re.compile(r".*?blogspot\.[A-Za-z0-9-]+"),
        )
        self.yourselfs = list(yourselfs)

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
            file = open(filepath, "r")
            for line in file.readlines():
                yield line.strip()
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
        result = self._judge_yourself(host)
        if result is not None:
            return result

        for black_rule in self.black_list:
            if black_rule.match(host):
                return True

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
        for filepath in self.yourselfs:
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


CN_IPv4 = get_cn_ipv4_network()


def judge(host: str) -> typing.Optional[bool]:
    """检查是否需要走代理"""
    result = None

    try:
        address = ipaddress.ip_address(host)
        if address.is_private:
            return False
        for network in CN_IPv4:
            if address in network:
                return False
    except ValueError:
        pass

    if host in cache:
        return True

    result = FilterRule().judge(host)

    if result is True:
        cache.add(host)
    return result


def add(host: str) -> None:
    """增加新的 host 进加速名单"""
    cache.add(host)
