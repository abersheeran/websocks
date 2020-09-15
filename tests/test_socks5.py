import os
import sys
import time
import socket
import atexit
import traceback
import subprocess

sys.path.insert(0, os.getcwd())

try:
    import socks

    socks.set_default_proxy(socks.PROXY_TYPE_SOCKS5, "127.0.0.1", 13128)
    socket.socket = socks.socksocket
except ImportError:
    sys.exit("You must install `socks` to run test.\nlike run `pip install pysocks`")
