import re
import json
from typing import Sequence, Dict, List

try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal

import yaml

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
    servers: Sequence[Dict[str, str]]
    """ WebSocks Server
    [
        {
            "protocol": "ws"|"wss",
            "username": "USERNAME",
            "password": "PASSWORD",
            "url": "URL",
        },
    ]
    """
    udp_server: Sequence[Dict[str, str]]
    """ UDP Server
    [
        {
            "protocol": "normal",
            "username": "USERNAME",
            "passoword": "PASSWORD",
            "host": "HOST",
            "port": "PORT",
            "algorithm": "AEAD-NAME"
        },
    ]
    """
    proxy_policy: Literal["AUTO", "PROXY", "DIRECT", "GFW"]
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

    def _set_default_value(self) -> None:
        self.setdefault("host", "127.0.0.1")
        self.setdefault("port", 3128)
        self.setdefault("proxy_policy", "AUTO")

    def from_json_file(self, filepath: str) -> None:
        self._set_default_value()
        with open(filepath) as file:
            self.update(json.load(file))

    def from_yaml_file(self, filepath: str) -> None:
        self._set_default_value()
        with open(filepath) as file:
            self.update(yaml.safe_load(file))


g = State()  # 全局变量
config = Config()  # 快捷方式 - 配置
