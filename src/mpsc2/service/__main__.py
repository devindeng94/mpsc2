"""Start the local service with explicit installation and map registries."""
import argparse
import asyncio
import json
from pathlib import Path
import signal
from . import Installation, NativeFactory, LocalServer


async def serve(args):
    config_path = Path(args.config).resolve()
    config = json.loads(config_path.read_text(encoding='utf-8'))
    def path(value):
        return (config_path.parent / value).resolve()
    installations = {name: Installation(path(value['root']), value['version'])
                     for name, value in config['installations'].items()}
    factory = NativeFactory(installations, {k: path(v) for k, v in config['maps'].items()}, path(config['output']))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass  # Windows asyncio.run handles KeyboardInterrupt and runs cleanup.
    token = path(config['controller_token_file']).read_text(encoding='ascii').strip()
    async with LocalServer(factory, controller_token=token, port=args.port) as server:
        print(json.dumps({'url': server.url, 'protocol': '1.0', 'scope': 'loopback'}), flush=True)
        await stop.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, help='Local registry JSON; paths relative to this file')
    parser.add_argument('--port', type=int, default=5000)
    args = parser.parse_args()
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
