import argparse
import json
from pathlib import Path
from . import data


def main():
    p=argparse.ArgumentParser(description='DataBrief数据导入与受限SQL核心（开发中）')
    p.add_argument('--db',default='data/databrief.sqlite3')
    commands=p.add_subparsers(dest='command',required=True)
    commands.add_parser('import').add_argument('file',type=Path)
    commands.add_parser('profile').add_argument('id')
    q=commands.add_parser('query');q.add_argument('id');q.add_argument('sql')
    args=p.parse_args();data.initialize(args.db)
    try:
        if args.command=='import':
            with args.file.open('rb') as f:raw=f.read(data.MAX_BYTES+1)
            result=data.import_csv(args.db,args.file.name,raw)
        elif args.command=='profile':
            result=data.dataset(args.db,args.id);result.pop('rows')
        else:result=data.execute(args.db,args.id,args.sql)
    except (ValueError,KeyError,OSError) as exc:p.exit(1,str(exc)+'\n')
    print(json.dumps(result,ensure_ascii=True,indent=2))
    if result.get('state')=='failed':raise SystemExit(1)


if __name__=='__main__':main()
