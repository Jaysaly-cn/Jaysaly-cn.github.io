"""python -m app.cli --db data/inbox.sqlite3 import sample.eml"""
import argparse
import json
from pathlib import Path
from . import store
from .ingest import MAX_BYTES


def main():
    parser = argparse.ArgumentParser(description='InboxToTasks 离线邮件导入（开发中）')
    parser.add_argument('--db', type=Path, default=Path('data/inbox.sqlite3'))
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('import').add_argument('file', type=Path)
    sub.add_parser('list')
    sub.add_parser('show').add_argument('id')
    args = parser.parse_args()
    try:
        store.initialize(args.db)
        if args.command == 'import':
            with args.file.open('rb') as source:
                raw = source.read(MAX_BYTES + 1)
            result = store.import_message(args.db, raw)
        elif args.command == 'list':
            result = store.messages(args.db)
        else:
            result = store.message(args.db, args.id)
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(1, str(exc) + '\n')
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
