import sys
import asyncio

if sys.platform == "win32":  # use IOCP in windows
    if sys.version_info.major >= 3 and sys.version_info.minor >= 7:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    else:
        asyncio.set_event_loop(asyncio.ProactorEventLoop())

    loop = asyncio.get_event_loop()

    def exception_handler(loop: asyncio.AbstractEventLoop, context: dict) -> None:
        if isinstance(context.get("exception"), ConnectionResetError):
            # Override the default handler's handling of this
            return  # nothing to do
        return loop.default_exception_handler(context)

    loop.set_exception_handler(exception_handler)

try:
    import uvloop

    uvloop.install()
except ImportError:
    pass
