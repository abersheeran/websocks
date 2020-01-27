import sys
import asyncio

if sys.platform == "win32":  # use IOCP in windows
    if sys.version_info.major >= 3 and sys.version_info.minor >= 7:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    else:
        asyncio.set_event_loop(asyncio.ProactorEventLoop())
else:  # try to use uvloop
    try:
        import uvloop

        uvloop.install()
    except ImportError:
        pass
