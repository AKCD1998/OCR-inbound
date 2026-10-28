"""Portable loopback review server. Heavy processing belongs in an HQ adapter."""
from __future__ import annotations

import argparse
import importlib
from pathlib import Path
import re
import sys

from .core import PrototypeStore
from .web import make_server


def load_processor(spec: str):
    """Load explicitly trusted operator-supplied Python code; never eval input."""
    if not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*',spec):
        raise ValueError('Processor must be module:callable')
    module,attribute=spec.split(':',1)
    processor=getattr(importlib.import_module(module),attribute)
    if not callable(processor):raise ValueError('Selected processor is not callable')
    return processor


def parser() -> argparse.ArgumentParser:
    cli=argparse.ArgumentParser(description='Source-bound document preparation and single final human review')
    commands=cli.add_subparsers(dest='command',required=True)
    serve=commands.add_parser('serve',help='Run the local final-review website')
    serve.add_argument('--store',type=Path,required=True,help='Private local evidence/database directory (keep outside Git)')
    serve.add_argument('--host',choices=('127.0.0.1','localhost'),default='127.0.0.1')
    serve.add_argument('--port',type=int,default=8877)
    serve.add_argument('--reviewer',required=True,help='Named person responsible for final review')
    mode=serve.add_mutually_exclusive_group(required=True)
    mode.add_argument('--demo',action='store_true',help='Seed synthetic PNG/PDF only; no OCR/model inference')
    mode.add_argument('--processor',metavar='MODULE:CALLABLE',help='Trusted background transport callback; heavy OCR must run on HQ')
    mode.add_argument('--hq-config',type=Path,metavar='PRIVATE_PROFILE',help='Private document-ai HQ profile JSON; heavy work stays on HQ')
    return cli


def main(argv=None) -> int:
    cli=parser();args=cli.parse_args(argv)
    if not 0<=args.port<=65535:cli.error('port must be between 0 and 65535')
    if not args.reviewer.strip():cli.error('a non-empty named reviewer is required')
    processor=None;store=None;server=None
    try:
        if args.demo:
            from .demo import demo_processor,prepare_demo_store
            prepare_demo_store(args.store.resolve());processor=demo_processor
        elif args.processor:processor=load_processor(args.processor)
        elif args.hq_config:
            from .hq_transport import HQProcessor
            processor=HQProcessor(args.hq_config)
        store=PrototypeStore(args.store,processor=processor)
        server=make_server(store,args.host,args.port,args.reviewer)
        if args.demo:
            from .demo import seed_demo
            seed_demo(store,args.reviewer)
            print('SYNTHETIC DEMO ONLY: no OCR, model inference, training or live ERP writes.',flush=True)
            print(f'Demo upload files: {store.root / "demo-inputs"}',flush=True)
        elif args.hq_config:
            print('HQ transport configured. Actual processing follows HQ resource admission and receipts.',flush=True)
        store.resume_pending()
        print(f'Document final review: http://127.0.0.1:{server.server_port}',flush=True)
        print('Local review only. Press Ctrl+C to close safely; no live ERP connection.',flush=True)
        server.serve_forever(poll_interval=.5)
    except KeyboardInterrupt:
        return 0
    except (OSError,ValueError,ImportError,AttributeError) as exc:
        print(f'Document AI could not start: {exc}',file=sys.stderr,flush=True)
        return 2
    finally:
        if server is not None:server.server_close()
        if store is not None:store.close(wait=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
