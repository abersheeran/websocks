import sys
import asyncio

try:
    import uvloop

    uvloop.install()
except ImportError:
    pass
