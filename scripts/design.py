#!/usr/bin/env python3
"""Run setup, evidence ingestion, model creation and deterministic handoff."""
import argparse
import json
import sys
from pathlib import Path
from common import url, write_json, read_json, plan_for, coverage, now


def doctor():
    from capture import doctor as browser_doctor
    return {'python':sys.version.split()[0],'pythonSupported':sys.version_info >= (3,10),**browser_doctor()}


def init_run(source, out, mode, maximum):
    source = url(source)
    run = Path(out).resolve()
    skill = Path(__file__).resolve().parent.parent
    if run == skill or run.is_relative_to(skill):
        raise ValueError('运行产物必须位于 Skill 外部')
    if (run/'plan.json').exists():
        existing = plan_for(run)
        if existing['originalUrl'] != source: raise ValueError('目录已有其他网站计划，改用新目录')
        return {'status':'unchanged','run':str(run),'plan':existing}
    if run.exists() and any(run.iterdir()): raise ValueError('目录非空且没有计划，改用新目录')
    if mode == 'single': cap = 1
    elif mode == 'standard': cap = maximum or 5
    else:
        if maximum is None: raise ValueError('extended 必须指定用户确认的 --max-pages')
        cap = maximum
    if cap < 1 or (mode == 'standard' and cap > 5): raise ValueError('页面上限无效；standard 最多 5 页')
    plan = {'schemaVersion':1, 'originalUrl':source, 'mode':mode, 'targetPages':min(3,cap),
        'maxPages':cap,'pages':[source], 'authorizedOrigins':[],
        'viewports':[{'name':'desktop','width':1440,'height':1000},{'name':'mobile','width':390,'height':844}],
        'selectionNotes':[], 'gaps':[], 'createdAt':now()}
    write_json(run/'plan.json',plan)
    write_json(run/'evidence'/'index.json',{'snapshots':[],'failures':[]})
    return {'status':'created','run':str(run),'next':'capture input page, inspect candidates, update plan.pages'}


def main(argv=None):
    if sys.version_info < (3,10): raise SystemExit('需要 Python 3.10+')
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    check=sub.add_parser('doctor',help='默认只做本地检测')
    start = sub.add_parser('init',help='创建可恢复的运行计划')
    start.add_argument('url'); start.add_argument('--out',required=True)
    start.add_argument('--mode',choices=['single','standard','extended'],default='standard')
    start.add_argument('--max-pages',type=int)
    for name in ('check-plan','coverage','build','export','verify'):
        cmd = sub.add_parser(name);cmd.add_argument('--run',required=True)
    incoming=sub.add_parser('capture',help='唯一本地 Chrome/CDP 采集入口')
    incoming.add_argument('--run',required=True);incoming.add_argument('--url');incoming.add_argument('--viewport')
    incoming.add_argument('--state',choices=['default','hover','focus'],default='default');incoming.add_argument('--selector')
    incoming.add_argument('--refresh',action='store_true');incoming.add_argument('--max-elements',type=int,default=1200)
    incoming.add_argument('--checkpoints',type=int,default=3);incoming.add_argument('--max-matched',type=int,default=80)
    args = parser.parse_args(argv)
    try:
        if args.command == 'doctor': result = doctor()
        elif args.command == 'init': result = init_run(args.url,args.out,args.mode,args.max_pages)
        elif args.command == 'check-plan':
            plan = plan_for(args.run);result = {'status':'valid','pages':plan['pages'],'maxPages':plan['maxPages']}
        elif args.command == 'capture':
            from capture import capture
            result=capture(args.run,args.url,args.viewport,args.state,args.selector,args.refresh,args.max_elements,args.checkpoints,args.max_matched)
        elif args.command == 'coverage':
            result = coverage(args.run);write_json(Path(args.run)/'evidence'/'coverage.json',result)
        elif args.command == 'build':
            from model import build
            path, model = build(args.run);result = {'status':'created','file':str(path),'tokens':len(model['tokens']),'components':len(model['components'])}
        elif args.command == 'export':
            from exporter import export
            result = {'status':'exported','files':export(args.run)}
        else:
            from exporter import verify
            result = verify(args.run);write_json(Path(args.run)/'verification.json',result)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 130 if result.get('cancelled') else 2 if result.get('status')=='partial' else 0
    except (ValueError,KeyError,TypeError,OSError) as error:
        print(json.dumps({'status':'error','message':str(error)},ensure_ascii=False),file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
