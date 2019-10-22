import socket
import sys
import traceback

try:
    import socks
    socks.set_default_proxy(socks.PROXY_TYPE_HTTP, "127.0.0.1", 3128)
    socket.socket = socks.socksocket
except ImportError:
    sys.exit("You must install `socks` to run test.\nlike run `pip install pysocks`")

try:
    sock = socket.create_connection(("abersheeran.com", 80))
    sock.sendall(b"GET / HTTP/1.1\r\nHost:abersheeran.com\r\n\r\n")
    print(sock.recv(4096))
except socket.error:
    traceback.print_exc()
finally:
    sock.close()
