import re
import sys
import json
from dataclasses import dataclass
from typing import Sequence, Dict, List

if sys.version_info[:2] < (3, 8):
    from typing_extensions import Literal
else:
    from typing import Literal

import yaml
import aiodns

from .utils import Singleton, State
from .algorithm import AEAD

TCP_FORMAT = re.compile(
    r"(?P<protocol>(ws|wss))://" + r"(?P<username>.+?):(?P<password>.+?)@(?P<url>.+)"
)

UDP_FORMAT = re.compile(
    r"(?P<protocol>(normal))://(?P<username>.+?):(?P<password>.+?)@(?P<host>.+):(?P<port>\d+)/\?algorithm=(?P<algorithm>("
    + "|".join(AEAD.keys())
    + r"))"
)


def convert_tcp_url(uri: str) -> Dict[str, str]:
    """
    convert "ws(s)://USERNAME:PASSWORD@URL*"
    """
    match = TCP_FORMAT.match(uri)
    assert match, "TCP uri format error"
    return match.groupdict()


def convert_udp_url(uri: str) -> Dict[str, str]:
    """
    convert "normal://USERNAME:PASSWORD@HOST:PORT/?algorithm=AEAD-NAME"
    """
    match = UDP_FORMAT.match(uri)
    assert match, "UDP uri format error"
    return match.groupdict()


@dataclass
class TCP:
    protocol: str
    username: str
    password: str
    url: str


@dataclass
class UDP:
    protocol: str
    username: str
    password: str
    host: str
    port: int
    algorithm: str


class Config(State, metaclass=Singleton):
    """
    客户端配置
    """

    host: str
    """
    监听地址
    """
    port: int
    """
    监听端口
    """
    proxy_policy: Literal["AUTO", "PROXY", "DIRECT", "GFW", "PREDNS"]
    """ 代理策略
    AUTO: 自动判断
    PROXY: 全部代理
    DIRECT: 全部不代理
    GFW: 仅代理 GFW 名单
    """
    rulefiles: List[str]
    """ 自定义规则文件
    每一个字符串都应该是一个规则文件的路径
    """

    tcp_server: TCP
    udp_server: UDP

    def _set_default_value(self) -> None:
        self.setdefault("host", "127.0.0.1")
        self.setdefault("port", 3128)
        self.setdefault("proxy_policy", "AUTO")
        self.setdefault("proxy_index", 0)

    def _update(self, data: dict) -> None:
        if len(data["servers"]) == 1:
            server = data["servers"][0]
        else:
            server = data["servers"][data.pop("server_index", 0)]
        if isinstance(server, str):
            self.tcp_server = TCP(**convert_tcp_url(server))
        elif isinstance(server, dict):
            self.tcp_server = TCP(**server)
        else:
            raise ValueError("Server Config 必须是一个 str 或者 dict")
        data.pop("servers")

        self.update(data)

    def from_json_file(self, filepath: str) -> None:
        self._set_default_value()
        with open(filepath) as file:
            self._update(json.load(file))

    def from_yaml_file(self, filepath: str) -> None:
        self._set_default_value()
        with open(filepath) as file:
            self._update(yaml.safe_load(file))


g = State()  # 全局变量
config = Config()  # 快捷方式 - 配置


g.resolver = aiodns.DNSResolver()
