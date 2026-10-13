"""Serve one finished demo directory on an ephemeral loopback port."""
import argparse
import functools
import json
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('run',type=Path);a=p.parse_args();folder=a.run.resolve()
assert (folder/'demo.html').is_file()
handler=functools.partial(SimpleHTTPRequestHandler,directory=str(folder))
server=ThreadingHTTPServer(('127.0.0.1',0),handler)
url=f'http://127.0.0.1:{server.server_port}/demo.html'
(folder/'preview-server.json').write_text(json.dumps({'url':url,'directory':str(folder)},indent=2))
print(url,flush=True)
server.serve_forever()
