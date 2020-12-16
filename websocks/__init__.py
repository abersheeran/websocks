try:
    import uvloop

    uvloop.install()
except ImportError:
    pass
