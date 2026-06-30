"""Process entrypoints: the ASGI app, the fleet worker, and the CLI.

These are the only places that compose the kernel + fleet + identity into a
running process. They are thin: all behaviour lives in the libraries they wire.
"""
