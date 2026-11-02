"""Selected incumbent CFB path; no unselected Monte Carlo challenger fallback."""
from models.current import common
from models.current.cfb import forecast

def load_schedule(card_date,as_of_utc):return common.schedule('cfb',card_date,as_of_utc)

def build_context(events,as_of_utc,allow_stale=False,overrides_path=None):
    if overrides_path:raise ValueError('VERSIONED_PACKAGE_REQUIRED')
    return common.context('cfb',events,as_of_utc)

def forecast_event(event,context,simulations=100000):return forecast(event,context,simulations)
