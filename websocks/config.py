import re
from dataclasses import dataclass
from typing import Dict

TCP_FORMAT = re.compile(
    r"(?P<protocol>(ws|wss))://" + r"(?P<username>.+?):(?P<password>.+?)@(?P<url>.+)"
)


def convert_tcp_url(uri: str) -> Dict[str, str]:
    """
    convert "ws(s)://USERNAME:PASSWORD@URL*"
    """
    match = TCP_FORMAT.match(uri)
    assert match, "TCP uri format error"
    return match.groupdict()


@dataclass
class TCP:
    protocol: str
    username: str
    password: str
    url: str
