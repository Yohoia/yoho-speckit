#!/usr/bin/env python3
"""Run setup, evidence ingestion, model creation and deterministic handoff."""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from common import url, write_json, read_json, plan_for, ingest, coverage, now


def doctor(cloud_status=False):
    result = {'python':sys.version.split()[0], 'pythonSupported':sys.version_info >= (3,10),
              'apiKeyAvailable':bool(os.environ.get('FIRECRAWL_API_KEY')),
              'hostBrowser':'Agent must inspect host capabilities',
              'connector':'Agent must inspect host capabilities',
              'firecrawlCli':{'installed':False,'authenticated':None,'cloudStatus':'not-checked'},
              'credentialPage':{'node':None,'dependenciesInstalled':False}}
    command = shutil.which('firecrawl')
    if command:
        result['firecrawlCli']['installed'] = True
    if command and cloud_status:
        try:
            proc = subprocess.run([command,'--status'],capture_output=True,text=True,timeout=15)
            output = proc.stdout.lower()
            result['firecrawlCli']['authenticated'] = 'authenticated' in output and 'not authenticated' not in output and 'unauthenticated' not in output
            result['firecrawlCli']['cloudStatus']='checked'
        except (OSError,subprocess.TimeoutExpired):
            result['firecrawlCli']['status'] = 'check-failed'
    node = shutil.which('node')
    if node:
        try:
            proc = subprocess.run([node,'--version'],capture_output=True,text=True,timeout=5)
            version = proc.stdout.strip().lstrip('v')
            numbers = tuple(int(x) for x in version.split('.')[:3])
            result['credentialPage']['node'] = version
            result['credentialPage']['nodeSupported'] = numbers >= (22,18,0)
        except (ValueError,OSError,subprocess.TimeoutExpired): pass
    result['credentialPage']['dependenciesInstalled'] = (Path(__file__).parent/'credential-ui'/'node_modules'/'@napi-rs'/'keyring').exists()
    return result


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
    check.add_argument('--cloud-status',action='store_true',help='显式查询 CLI 云端账户状态')
    start = sub.add_parser('init',help='创建可恢复的运行计划')
    start.add_argument('url'); start.add_argument('--out',required=True)
    start.add_argument('--mode',choices=['single','standard','extended'],default='standard')
    start.add_argument('--max-pages',type=int)
    for name in ('check-plan','coverage','build','export','verify'):
        cmd = sub.add_parser(name);cmd.add_argument('--run',required=True)
    incoming = sub.add_parser('ingest',help='导入共用探针 JSON')
    incoming.add_argument('--run',required=True);incoming.add_argument('--input',required=True)
    incoming.add_argument('--backend',default='browser');incoming.add_argument('--viewport-name',required=True)
    incoming.add_argument('--state',default='default');incoming.add_argument('--requested-url')
    incoming.add_argument('--screenshot');incoming.add_argument('--replace',action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'doctor': result = doctor(args.cloud_status)
        elif args.command == 'init': result = init_run(args.url,args.out,args.mode,args.max_pages)
        elif args.command == 'check-plan':
            plan = plan_for(args.run);result = {'status':'valid','pages':plan['pages'],'maxPages':plan['maxPages']}
        elif args.command == 'ingest': result = ingest(args.run,read_json(args.input),args.backend,args.viewport_name,args.state,args.requested_url,args.screenshot,args.replace)
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
        return 0
    except (ValueError,KeyError,TypeError,OSError) as error:
        print(json.dumps({'status':'error','message':str(error)},ensure_ascii=False),file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
