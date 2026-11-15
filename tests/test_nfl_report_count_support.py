import pandas as pd
import pytest

from research.missingness.nfl_report_count import FEATURE, support, transform, metrics


def test_support_uses_only_observations_in_native_training_population():
    f = pd.DataFrame({FEATURE:[0,1,2], "home_win":[0,1,None],
                      "home_margin":[-1,1,0], "total_points":[3,3,6]})
    assert support(f) == {0:1,1:1}


def test_only_out_of_support_feature_is_changed_and_parent_is_intact():
    frame=pd.DataFrame({FEATURE:[0.,1.,2.], "home_margin":[21,-3,7]})
    successor=transform(frame,{0:55,1:2})
    assert successor[FEATURE].tolist()==[0.,1.,1.]
    assert successor["home_margin"].equals(frame["home_margin"])
    assert frame[FEATURE].tolist()==[0.,1.,2.]


@pytest.mark.parametrize("levels", [{},{0:10,2:1},{0:1,1:0},{3:1}])
def test_ambiguous_or_invalid_counts_refuse(levels):
    with pytest.raises(ValueError,match="TRAINING_SUPPORT"):
        transform(pd.DataFrame({FEATURE:[2]}),levels)


def test_missing_is_not_count_zero_and_empty_evaluation_has_no_score():
    with pytest.raises(ValueError,match="UNSUPPORTED_INPUT_COUNT"):
        transform(pd.DataFrame({FEATURE:[None]}),{0:100})
    assert metrics(pd.DataFrame(),"candidate_") is None
