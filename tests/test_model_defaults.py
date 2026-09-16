import copy,json,tempfile,unittest
from pathlib import Path
from pipelines.cards.selection import select,require_default,SelectionError,CATALOG,inventory
from pipelines.cards.selected import apply_default
from scripts.generate_card_force import normalize,render_md

class ModelDefaults(unittest.TestCase):
    def test_verified_defaults(self):
        self.assertEqual(select('nfl')['default_model_id'],'nfl.integrated_context.qb.v1.research')
        self.assertEqual(select('wnba')['metrics']['n'],1633)
        self.assertEqual(select('mlb')['selection_status'],'TESTED_INCUMBENT_RETAINED')
    def test_unverified_leagues_refuse(self):
        for league in ['nba','nhl','mls']:
            with self.assertRaisesRegex(SelectionError,'NO_VERIFIED_TESTED_DEFAULT'):select(league)
    def test_target_does_not_inherit_winner_evidence(self):
        for league in ['nfl','mlb','nba']:
            with self.assertRaisesRegex(SelectionError,'NO_TESTED_DEFAULT_FOR_PRODUCT'):select(league,'total')
    def test_wnba_target_specific_metrics(self):
        self.assertIn('mae',select('wnba','total')['metrics'])
        self.assertNotIn('brier',select('wnba','total')['metrics'])
    def test_cfb_week1_scope(self):
        self.assertIn('week1_shadow',select('cfb',week=1,division='FBS_VS_FBS')['default_model_id'])
        self.assertIn('elo_form',select('cfb',week=2,division='FBS_VS_FBS')['default_model_id'])
    def test_cfb_crossdivision_refusal(self):
        with self.assertRaisesRegex(SelectionError,'SUBDIVISION'):select('cfb',week=2,division='FCS_VS_FBS')
    def test_cfb_unspecified_week_refusal(self):
        with self.assertRaisesRegex(SelectionError,'WEEK_SCOPE'):select('cfb',division='FBS_VS_FBS')
    def test_failed_candidate_cannot_default(self):
        c=json.loads(CATALOG.read_text());c['profiles']['nfl:winner']['selection_status']='FAILED'
        with self.assertRaisesRegex(SelectionError,'INELIGIBLE_DEFAULT'):select('nfl',catalog=c)
    def test_missing_evidence_not_tested(self):
        c=json.loads(CATALOG.read_text());c['profiles']['nfl:winner']['evidence']=[]
        with self.assertRaisesRegex(SelectionError,'EVIDENCE_REQUIRED'):select('nfl',catalog=c)
    def test_evidence_hash_drift(self):
        c=json.loads(CATALOG.read_text());c['profiles']['nfl:winner']['evidence'][0]['sha256']='wrong'
        with self.assertRaisesRegex(SelectionError,'EVIDENCE_DRIFT'):select('nfl',catalog=c)
    def test_challenger_cannot_replace_default(self):
        with self.assertRaisesRegex(SelectionError,'CHALLENGER_CANNOT_HEADLINE'):
            require_default('nfl','nfl.integrated_context.combined.v1.research')
    def test_inventory_covers_seven_sports_and_blocks_honestly(self):
        x=inventory()['profiles'];self.assertEqual(len({k.split(':')[0] for k in x}),7)
        self.assertIsNone(x['nhl:winner']['default_model_id'])
    def fixture(self):
        e={'event_id':'synthetic','home_team':'H','away_team':'A','start_time_utc':'2099-01-01T00:00:00Z'}
        raw={'model_id':'old_composite','model_winner':'H','model_p':.6,'sim_p':.4,'dose':0.,'diagnostics':{'simulation_model_id':'mlb.winner.CHAMPION_V13','sim_home_win':.4,'analytic_home_win':.6},'warnings':[]}
        return e,raw
    def test_mlb_uses_selected_direction_not_challenger(self):
        e,raw=self.fixture();r=apply_default('mlb',e,raw)
        self.assertEqual(r['model_winner'],'A');self.assertEqual(r['model_p'],.6)
        self.assertEqual(r['diagnostics']['challengers'][0]['home_win_probability'],.6)
        self.assertEqual(raw['model_id'],'old_composite');self.assertIsNone(r['analytic_p'])
    def test_monte_carlo_is_not_analytic_convergence(self):
        e,raw=self.fixture();r=normalize(e,apply_default('mlb',e,raw))
        self.assertIsNone(r['analytic_p']);self.assertIsNone(r['analytic_sim_gap_pp'])
        self.assertEqual(r['analytic_sim_divergence'],'NOT_APPLICABLE_MC_ONLY')
        card={'league':'MLB','card_date':'2099-01-01','pregame_coverage':1.,'forecasts':[r],'incidents':[]}
        text=render_md(card);self.assertIn('NOT_APPLICABLE_MC_ONLY',text)
    def test_selection_does_not_enable_action(self):
        for p in inventory()['profiles'].values():self.assertFalse(p['action_authority']);self.assertFalse(p['official_release'])

if __name__=='__main__':unittest.main()
