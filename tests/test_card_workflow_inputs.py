import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('inputs', ROOT/'scripts/prepare_card_workflow_inputs.py')
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def bundle(self, league='cfb', extra=None, package=None):
        self.package = package or {'schema':'sports.current_research_package.v1','league':league,
          'action_authority':False,'captured_at_utc':'2020-01-01T00:00:00Z','ttl_hours':6,
          'source_fetches':[{'source':'https://example.org/source','sha256':'a'*64,'fetched_at_utc':'2020-01-01T00:00:00Z'}]}
        path=self.root/'input.zip'
        with zipfile.ZipFile(path,'w') as z:
            z.writestr(f'packages/{league}/package.json', json.dumps(self.package))
            for key,value in (extra or {}).items(): z.writestr(key,value)
        return path,hashlib.sha256(path.read_bytes()).hexdigest()
    def test_request_scope(self):
        M.validate_request('mlb')
        for league in ['cfb','nfl','wnba','nba','nhl']:
            with self.subTest(league=league), self.assertRaises(ValueError): M.validate_request(league)
        for league in ['nba','nhl']:
            with self.subTest(league=league):
                with self.assertRaisesRegex(ValueError,'OPT_IN'): M.validate_request(league,'12','a'*64)
                M.validate_request(league,'12','a'*64,True)
        for league in ['nfl','wnba','cfb','mlb']:
            with self.subTest(league=league), self.assertRaisesRegex(ValueError,'SCOPE'):
                M.validate_request(league,'12','a'*64,True)
    def test_invalid_artifact_identity(self):
        for args in [('cfb','12',''),('cfb','','a'*64),('cfb','12\ninjected','a'*64),('cfb','0','a'*64),('cfb','12','q'*64)]:
            with self.subTest(args=args), self.assertRaises(ValueError): M.validate_request(*args)
    def test_preserves_source_bytes_and_ttl(self):
        path,h=self.bundle()
        env,receipt=M.restore(path,h,self.root/'out','cfb')
        saved=Path(env['SPORTS_RESEARCH_PACKAGE_DIR'])/'cfb/package.json'
        self.assertEqual(json.loads(saved.read_text()), self.package)
        self.assertEqual(saved.read_bytes(),zipfile.ZipFile(path).read('packages/cfb/package.json'))
        self.assertFalse(receipt['acquisition_performed']); self.assertFalse(receipt['refit_performed'])
        self.assertEqual(receipt['freshness_and_model_validation'],'DEFERRED_TO_UNCHANGED_RUNNER')
        self.assertNotIn('SPORTS_INITIAL_BASELINES',env)
    def test_hash_refusal_before_extraction(self):
        path,h=self.bundle()
        with self.assertRaisesRegex(ValueError,'HASH'): M.restore(path,'b'*64,self.root/'out','cfb')
        self.assertFalse((self.root/'out').exists())
    def test_missing_or_wrong_league(self):
        path,h=self.bundle()
        with self.assertRaisesRegex(ValueError,'MISSING'): M.restore(path,h,self.root/'out','nhl')
        package=dict(self.package,league='nba');path,h=self.bundle(package=package)
        with self.assertRaisesRegex(ValueError,'IDENTITY'): M.restore(path,h,self.root/'out','cfb')
    def test_rejects_action_authority(self):
        path,h=self.bundle(package={'schema':'sports.current_research_package.v1','league':'cfb','action_authority':True})
        with self.assertRaisesRegex(ValueError,'IDENTITY'): M.restore(path,h,self.root/'out','cfb')
    def test_unsafe_members(self):
        for name in ['../escape','packages/../escape','/packages/x','packages\\x','scripts/exploit.py','packages/x\ninjected']:
            with self.subTest(name=name):
                path,h=self.bundle(extra={name:'bad'})
                with self.assertRaisesRegex(ValueError,'UNSAFE'): M.restore(path,h,self.root/'out','cfb')
                self.assertFalse((self.root/'out').exists())
    def test_symlink_refusal(self):
        path,h=self.bundle();info=zipfile.ZipInfo('packages/link');info.create_system=3;info.external_attr=(stat.S_IFLNK|0o777)<<16
        with zipfile.ZipFile(path,'a') as z:z.writestr(info,'/tmp/target')
        h=hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,'UNSAFE'):M.restore(path,h,self.root/'out','cfb')
    def test_duplicate_refusal(self):
        path,h=self.bundle()
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with zipfile.ZipFile(path,'a') as z:z.writestr('packages/cfb/package.json','{}')
        h=hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,'UNSAFE'):M.restore(path,h,self.root/'out','cfb')
    def test_immutable_destination(self):
        path,h=self.bundle();M.restore(path,h,self.root/'out','cfb')
        with self.assertRaises(FileExistsError):M.restore(path,h,self.root/'out','cfb')
    def test_nfl_dependency_binding(self):
        p={'schema':'nfl.event_package.v1','model_path':'../context/model.json','recovered_parameters_path':'../context/parameters.json'}
        path,h=self.bundle('nfl',{'packages/context/model.json':'{}','packages/context/parameters.json':'{}'},p)
        env,r=M.restore(path,h,self.root/'out','nfl')
        self.assertTrue(Path(env['NFL_CONTEXT_PACKAGE']).is_file());self.assertNotIn('SPORTS_RESEARCH_PACKAGE_DIR',env)
    def test_nfl_dependency_escape(self):
        p={'schema':'nfl.event_package.v1','model_path':'../../../secret','recovered_parameters_path':'other.json'}
        path,h=self.bundle('nfl',package=p)
        with self.assertRaisesRegex(ValueError,'DEPENDENCY'):M.restore(path,h,self.root/'out','nfl')


class WorkflowContract(unittest.TestCase):
    def test_workflow_dependencies_and_package_gate(self):
        w=(ROOT/'.github/workflows/diagnostic-shadow-card.yml').read_text()
        self.assertIn('python-version: "3.12"',w)
        self.assertIn('pip install -r requirements-consolidated.txt',w)
        self.assertNotIn('pip install -r requirements.txt',w)
        self.assertIn('validate_request(league, package_artifact_id, package_archive_sha256, initial == "true")',w)
        self.assertIn('args+=(--initial-research-baselines)',w)
        self.assertIn('--output-dir output/card "${args[@]}"',w)
        self.assertIn('repos/$GITHUB_REPOSITORY/actions/artifacts/$PACKAGE_ARTIFACT_ID/zip',w)
        self.assertNotIn('schedule:',w)
        for scope in ['INPUT','DISPATCH']:
            for field in ['PACKAGE_ARTIFACT_ID','PACKAGE_ARCHIVE_SHA256','INITIAL_RESEARCH_BASELINES']:
                self.assertIn(f'{scope}_{field}:',w)
        self.assertIn('req.get("package_artifact_id")',w)
        self.assertIn('Register priority-league prospective research card',w)
        self.assertIn('Register pregame MLB calibration card',w)


class RealRunnerOutputIntegration(unittest.TestCase):
    """Execute the unchanged PR62 runner through the workflow's shell block.

    Only the sports adapter is replaced by a minimal verified-empty fixture.
    Runner directory creation, generation, formatting and file writes are real.
    """
    def run_workflow(self, precreate=False, fail_adapter=False):
        import os, subprocess, sys, textwrap
        workflow=(ROOT/'.github/workflows/diagnostic-shadow-card.yml').read_text()
        step=workflow.split('      - name: Generate diagnostic card',1)[1].split('      - name:',1)[0]
        shell=textwrap.dedent(step.split('        run: |\n',1)[1])
        runner=ROOT/'scripts/generate_card_force.py'
        if not runner.exists():runner=ROOT.parent/'base/scripts/generate_card_force.py'
        self.assertTrue(runner.is_file(), 'Real unchanged runner is required; no stand-in runner permitted')
        with tempfile.TemporaryDirectory() as tmp:
            work=Path(tmp);(work/'scripts').mkdir();(work/'output/run-evidence').mkdir(parents=True)
            (work/'output/run-evidence/package-inputs.json').write_text('{"acquisition_performed":false}')
            if precreate:(work/'output/card').mkdir()
            wrapper = "import importlib.util,os,types\n"
            wrapper += "spec=importlib.util.spec_from_file_location('real_card',os.environ['REAL_RUNNER'])\n"
            wrapper += "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)\n"
            if fail_adapter:
                wrapper += "def reject(*a): raise ValueError('SYNTHETIC_ADAPTER_FAILURE')\nm.load_adapter=reject\n"
            else:
                wrapper += "adapter=types.SimpleNamespace(load_schedule=lambda *a: [],build_context=lambda *a: {'pit_provenance':{'source_fetches':[{'fetched_at_utc':'2026-01-01T00:00:00Z'}]}})\n"
                wrapper += "m.load_adapter=lambda league: adapter\n"
            wrapper += "m.main()\n"
            (work/'scripts/generate_card_force.py').write_text(wrapper)
            env=dict(os.environ,REAL_RUNNER=str(runner),CARD_DATE='2026-01-01',LEAGUE='cfb',AS_OF_UTC='2026-01-01T00:00:00Z',SIMULATION_COUNT='100000',INITIAL_RESEARCH='false',GITHUB_OUTPUT=str(work/'step-output'))
            result=subprocess.run(['bash','-c',shell],cwd=work,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            files={str(p.relative_to(work)):p.read_text() for p in (work/'output/card').glob('*') if p.is_file()}
            return files,(work/'step-output').read_text()
    def test_fixed_shell_allows_real_runner_to_create_directory(self):
        files,outputs=self.run_workflow()
        self.assertIn('exit_code=0',outputs)
        self.assertIn('output/card/diagnostic_card.json',files)
        card=json.loads(files['output/card/diagnostic_card.json'])
        self.assertEqual(card['scheduled_game_count'],0)
        self.assertEqual(card['forecast_count'],0)
        self.assertIn('output/card/package-inputs.json',files)
        self.assertIn('output/card/run.log',files)
    def test_precreated_output_reproduces_original_failure(self):
        files,outputs=self.run_workflow(precreate=True)
        self.assertIn('exit_code=1',outputs)
        self.assertNotIn('output/card/diagnostic_card.json',files)
        self.assertIn('FileExistsError',files['output/card/run.log'])
    def test_runner_failure_preserves_log_and_receipt(self):
        files,outputs=self.run_workflow(fail_adapter=True)
        self.assertIn('exit_code=1',outputs)
        self.assertIn('SYNTHETIC_ADAPTER_FAILURE',files['output/card/run.log'])
        self.assertIn('output/card/package-inputs.json',files)
        self.assertNotIn('output/card/diagnostic_card.json',files)


class ResolveOutputSafety(unittest.TestCase):
    def test_all_request_channels_reject_newline_output_values(self):
        import os, sys, contextlib, io
        from unittest.mock import patch
        w=(ROOT/'.github/workflows/diagnostic-shadow-card.yml').read_text()
        resolve=w.split('      - name: Resolve request',1)[1].split('      - name:',1)[0]
        import textwrap
        script=textwrap.dedent(resolve.split("          python - <<'PY'\n",1)[1].split('\n          PY',1)[0])
        sys.path.insert(0,str(ROOT))
        try:
            for channel,prefix in [('workflow_dispatch','INPUT_'),('repository_dispatch','DISPATCH_')]:
                for field in ['CARD_DATE','AS_OF_UTC','SIMULATION_COUNT','MODE','PUBLISH_SUMMARY']:
                    with self.subTest(channel=channel,field=field), tempfile.TemporaryDirectory() as tmp:
                        env={'EVENT_NAME':channel,'GITHUB_RUN_ID':'1','GITHUB_OUTPUT':str(Path(tmp)/'outputs'),prefix+'CARD_DATE':'2026-01-01',prefix+'LEAGUE':'mlb',prefix+'AS_OF_UTC':'2026-01-01T00:00:00Z',prefix+'SIMULATION_COUNT':'100000',prefix+'MODE':'diagnostic_shadow',prefix+'PUBLISH_SUMMARY':'false'}
                        env[prefix+field]='value\ninjected=value'
                        with patch.dict(os.environ,env,clear=True), contextlib.redirect_stdout(io.StringIO()):
                            with self.assertRaisesRegex(SystemExit,'MULTILINE_WORKFLOW_OUTPUT_REFUSED'):exec(compile(script,'resolve','exec'),{})
                        self.assertFalse(Path(env['GITHUB_OUTPUT']).exists())
        finally:sys.path.pop(0)


if __name__=='__main__':unittest.main()
