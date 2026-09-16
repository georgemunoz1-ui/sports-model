#!/usr/bin/env python3
from __future__ import annotations

MODULE_ID = 'execution_readiness'
import argparse, importlib.util, json, os, sys
from pathlib import Path

PACKAGE_IMPORTS = {"pandas":"pandas","pyarrow":"pyarrow","numpy":"numpy","scikit-learn":"sklearn"}

def check(args):
    checks={"python_runtime":sys.version_info >= (3,11),"required_packages":{},"required_files":{},"required_modules":{},"output_path_writable":True}
    for pkg in args.require_package:
        mod=PACKAGE_IMPORTS.get(pkg,pkg)
        checks["required_packages"][pkg]=importlib.util.find_spec(mod) is not None
    for p in args.require_file:
        checks["required_files"][p]=Path(p).is_file() and os.access(p,os.R_OK)
    for m in args.require_module:
        checks["required_modules"][m]=importlib.util.find_spec(m) is not None
    if args.output_dir:
        out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
        probe=out/'.execution_readiness_probe'
        try:
            probe.write_text('ok'); probe.unlink()
        except OSError:
            checks["output_path_writable"]=False
    failures=[]
    if not checks["python_runtime"]: failures.append('PYTHON_RUNTIME_UNSUPPORTED')
    failures += [f'PACKAGE_MISSING:{k}' for k,v in checks['required_packages'].items() if not v]
    failures += [f'FILE_UNAVAILABLE:{k}' for k,v in checks['required_files'].items() if not v]
    failures += [f'MODULE_UNAVAILABLE:{k}' for k,v in checks['required_modules'].items() if not v]
    if not checks['output_path_writable']: failures.append('OUTPUT_PATH_NOT_WRITABLE')
    return {"schema":"ops.execution_readiness.v1","league":args.league,"checks":checks,"ready":not failures,"failures":failures}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--league',required=True); p.add_argument('--require-file',action='append',default=[]); p.add_argument('--require-module',action='append',default=[]); p.add_argument('--require-package',action='append',default=[]); p.add_argument('--output-dir',default='run_artifacts'); p.add_argument('--report')
    a=p.parse_args(); report=check(a)
    if a.report:
        Path(a.report).parent.mkdir(parents=True,exist_ok=True); Path(a.report).write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(report,sort_keys=True))
    if not report['ready']: raise SystemExit('EXECUTION_ENVIRONMENT_UNAVAILABLE:'+','.join(report['failures']))
if __name__=='__main__': main()
