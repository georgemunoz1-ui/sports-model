"""Independent targeted synthetic checks; not model/hosted acceptance evidence."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO=Path('/workspace/scratch/4d9e36f4eb71/repair-evidence-review')
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(REPO))
from scripts import record_finding_successor as h
spec=importlib.util.spec_from_file_location('fixture_module',REPO/'tests/test_finding_successor.py')
f=importlib.util.module_from_spec(spec); spec.loader.exec_module(f)
expected='9371f44cad79444c899496ec308d79ac09153bc14aa507ccb6f36105c54e88e4'
assert hashlib.sha256((REPO/'scripts/record_finding_successor.py').read_bytes()).hexdigest()==expected

def setup(name):
    root=Path(tempfile.mkdtemp(prefix='verified-'+name+'-',dir=OUT))
    f.fixture(root)
    (root/'.gitignore').write_text('__pycache__/\n.pytest_cache/\nignored_input.py\n*.log\n')
    for name in ('tests','research/tests','research/cfb_binary_isotonic_proposal','scripts'):
        (root/name).mkdir(parents=True,exist_ok=True)
    for name in ('research','research/tests','research/cfb_binary_isotonic_proposal'):
        (root/name/'__init__.py').write_text('')
    shutil.copyfile(REPO/'scripts/record_finding_successor.py',root/'scripts/record_finding_successor.py')
    shutil.copyfile(REPO/'research/finding_evidence.py',root/'research/finding_evidence.py')
    for name in ('tests/test_one.py','research/tests/test_other.py','research/cfb_binary_isotonic_proposal/test_binary_isotonic_repair.py'):
        (root/name).write_text('def test_one():\n    assert True\n')
    (root/'research/test_unit.py').write_text('import unittest\nclass TestOne(unittest.TestCase):\n    def test_pass(self): self.assertTrue(True)\n')
    return root

results=[]
def check(name,prepare,expect_success=False,expected_reason=None,environment=None):
    root=setup(name); prepare(root)
    before={name:(root/name).read_bytes() for name in ('parent.json','old-receipt.json','old.log')}
    sha=h.file_ref(root,root/'parent.json')['sha256']
    old_env=dict(os.environ)
    error=None
    try:
        if environment: os.environ.update(environment)
        h.record_successor(root,'parent.json',sha,'successor')
    except Exception as exc: error=type(exc).__name__+':'+str(exc)
    finally:
        os.environ.clear();os.environ.update(old_env)
    packet=root/'successor/finding-evidence.json'; receipt=root/'successor/acceptance.json'
    r=json.loads(receipt.read_text()) if receipt.exists() else None
    assert packet.exists()==expect_success,(name,error,r)
    if expect_success:
        assert error is None and r['exit_code']==0 and r['failure'] is None,(name,error,r)
        for key,value in before.items(): assert (root/key).read_bytes()==value
        rows=json.loads(packet.read_text())
        for row in rows:
            assert row['supersedes']==dict(h.file_ref(root,root/'parent.json'),finding_id=row['finding_id'])
            for key in ('model_promotion_granted','predictive_validation_granted','publication_allowed','action_authority'):
                assert row[key] is False
            assert row['wagering_authority']=='OFF'
        assert r['hosted_verification']=='PENDING' and r['durable_archive_verified'] is False
        assert all(not ref['path'].startswith('successor/') for ref in r['sources'])
    else:
        assert error is not None,name
        if expected_reason: assert expected_reason in error,(name,error)
        if r: assert r['exit_code']==1 and r['failure'],(name,error,r)
    results.append({'case':name,'passed':True,'root':str(root),'error':error,
                    'packet_created':packet.exists(),'receipt_exit_code':r and r['exit_code'],
                    'receipt_failure':r and r['failure']})

def unit(root,decorator,statement):
    (root/'research/test_unit.py').write_text('import unittest\nclass TestOne(unittest.TestCase):\n    '+decorator+'\n    def test_pass(self): '+statement+'\n')

def mutate_ignored(root):
    (root/'ignored_input.py').write_text('value=1\n')
    (root/'tests/test_one.py').write_text('from pathlib import Path\ndef test_one():\n    p=Path("ignored_input.py")\n    assert p.read_text()=="value=1\\n"\n    p.write_text("value=999\\n")\n')

def historical_drift(root):
    (root/'tests/test_one.py').write_text('from pathlib import Path\ndef test_one():\n    Path("old.log").write_text("corrupt historical evidence\\n")\n')

def omitted_failure(root):
    (root/'tests/test_bad.py').write_text('def test_bad():\n    assert False\n')

def config_omit(root):
    omitted_failure(root)
    (root/'pytest.ini').write_text('[pytest]\naddopts=-k test_one\n')

def plugin_omit(root):
    omitted_failure(root)
    (root/'conftest.py').write_text('def pytest_collection_modifyitems(config,items):\n    dropped=[i for i in items if "test_bad" in i.nodeid]\n    items[:]=[i for i in items if i not in dropped]\n    config.hook.pytest_deselected(items=dropped)\n')

def history(root,kind):
    rows=json.loads((root/'parent.json').read_text())
    older=json.loads(json.dumps(rows))
    if kind=='missing_id': older[0]['finding_id']='OTHER'
    (root/'older.json').write_text(json.dumps(older))
    rows[0]['supersedes']=dict(h.file_ref(root,root/'older.json'),finding_id=rows[0]['finding_id'])
    (root/'parent.json').write_text(json.dumps(rows))
    if kind=='tampered': (root/'older.json').write_text('[]')

def authority(root):
    rows=json.loads((root/'parent.json').read_text())
    rows[0].update(model_promotion_granted=True,wagering_authority='ON',unrelated_authority=True)
    (root/'parent.json').write_text(json.dumps(rows))

check('normal',lambda r:None,True)
check('unit-skip',lambda r:unit(r,'@unittest.skip("synthetic")','pass'),expected_reason='ACCEPTANCE_TEST_FAILED')
check('unit-expected-failure',lambda r:unit(r,'@unittest.expectedFailure','self.fail("synthetic")'),expected_reason='ACCEPTANCE_TEST_FAILED')
check('unit-zero',lambda r:(r/'research/test_unit.py').unlink(),expected_reason='ACCEPTANCE_TEST_FAILED')
check('pytest-skip',lambda r:(r/'tests/test_one.py').write_text('import pytest\n@pytest.mark.skip(reason="synthetic")\ndef test_one(): pass\n'),expected_reason='JUNIT_NOT_COMPLETE_PASS')
check('actual-failure',omitted_failure,expected_reason='ACCEPTANCE_TEST_FAILED')
check('env-deselect',omitted_failure,expected_reason='PYTEST_ADDOPTS_MUST_BE_EMPTY',environment={'PYTEST_ADDOPTS':'-k test_one'})
check('config-deselect-overridden',config_omit,expected_reason='ACCEPTANCE_TEST_FAILED')
check('plugin-deselect',plugin_omit,expected_reason='ACCEPTANCE_TEST_FAILED')
check('ignored-source-drift',mutate_ignored,expected_reason='SOURCE_CHANGED_DURING_ACCEPTANCE')
check('historical-log-drift',historical_drift,expected_reason='HISTORICAL_EVIDENCE_HASH_MISMATCH')
check('ancestor-tamper',lambda r:history(r,'tampered'),expected_reason='HISTORICAL_EVIDENCE_HASH_MISMATCH')
check('ancestor-missing-id',lambda r:history(r,'missing_id'),expected_reason='HISTORICAL_FINDING_IDENTITY_MISMATCH')
check('inherited-authority-sanitized',authority,True)

for name,xml in [('junit-suite-error','<testsuite tests="1" failures="0" errors="1" skipped="0"><error/><testcase name="good"/></testsuite>'),
                 ('junit-failure-counter','<testsuite tests="1" failures="1" errors="0" skipped="0"><testcase name="good"/></testsuite>')]:
    path=OUT/(name+'-revision.xml');path.write_text(xml)
    try: h.junit_counts(path)
    except ValueError as exc: results.append({'case':name,'passed':True,'error':str(exc)})
    else: raise AssertionError(name+' accepted')

assert hashlib.sha256((REPO/'scripts/record_finding_successor.py').read_bytes()).hexdigest()==expected
report={'schema':'independent-helper-review-v1','scope':'SYNTHETIC_TARGETED_SOFTWARE_TESTS_ONLY',
 'helper_sha256':expected,'helper_tests_sha256':hashlib.sha256((REPO/'tests/test_finding_successor.py').read_bytes()).hexdigest(),
 'passed_cases':len(results),'cases':results,'full_acceptance_run':False,'remote_writes':False,'predictive_validation_granted':False}
(OUT/'verified_revision.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
