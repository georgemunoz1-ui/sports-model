"""Narrow independent #95 PR-trigger review. No workflow dispatch or network."""
import itertools,os,subprocess
from pathlib import Path
import yaml
REPO=Path(os.environ['VERIFY_REPO'])
W=yaml.load((REPO/'.github/workflows/daily-operations-preflight.yml').read_text(),Loader=yaml.BaseLoader)

def test_only_expected_triggers_and_exact_capture_paths():
 assert set(W['on'])=={'pull_request','workflow_dispatch','schedule'}
 assert set(W['on']['pull_request']['paths'])=={
 '.github/workflows/daily-operations-preflight.yml','scripts/capture_operational_inputs.py',
 'scripts/validate_operational_capture.py','scripts/operational_capture_contract.py',
 'scripts/recovery_capture.py','tests/test_operational_capture_validation.py','tests/test_recovery_governance.py'}
 assert W['on']['schedule']==[{'cron':'30 13 * * *'}]

def test_permissions_and_no_authority_bearing_steps():
 assert W['permissions']=={'contents':'read'}
 assert set(W['jobs'])=={'preflight'}
 job=W['jobs']['preflight'];assert 'permissions' not in job and 'environment' not in job
 steps=job['steps'];assert [s['uses'] for s in steps if 'uses' in s]==['actions/checkout@v4','actions/setup-python@v5','actions/upload-artifact@v4']
 shell='\n'.join(s.get('run','') for s in steps)
 for forbidden in ['secrets.','git push','gh pr','generate_card','register_selection','workflow_dispatch','--live','write-all','pull_request_target']:
  assert forbidden not in shell
 assert steps[2]['run'].strip().splitlines()==['set -o pipefail','python scripts/capture_operational_inputs.py --output "$RUNNER_TEMP/sports-inputs" 2>&1 | tee "$RUNNER_TEMP/capture.log"']
 upload=next(s for s in steps if s.get('id')=='evidence')
 assert upload['if']=='always()' and upload['with']['if-no-files-found']=='error'
 assert upload['with']['retention-days']=='30'

def test_concurrency_cannot_share_pr_and_daily_group():
 assert W['concurrency']=={'group':"daily-sports-operations-preflight-${{ github.event.pull_request.number || 'scheduled-manual' }}",'cancel-in-progress':'false'}
 assert 'daily-sports-operations-preflight-95'!='daily-sports-operations-preflight-scheduled-manual'

def test_actual_shell_gate_all_125_outcome_combinations():
 final=W['jobs']['preflight']['steps'][-1];assert final['if']=='always()'
 states=['success','failure','skipped','cancelled','']
 for values in itertools.product(states,repeat=3):
  script=final['run']
  for name,state in zip(['capture','checks','evidence'],values):script=script.replace('${{ steps.'+name+'.outcome }}',state)
  run=subprocess.run(['bash','-e','-o','pipefail','-c',script],capture_output=True,text=True)
  assert (run.returncode==0)==all(v=='success' for v in values),(values,run.stdout,run.stderr)
