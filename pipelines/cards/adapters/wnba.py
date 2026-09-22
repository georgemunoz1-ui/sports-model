"""Selected WNBA incumbent; fresh source-bound state and genuine winner draws."""
from models.current import common
from models.current.wnba import forecast

def load_schedule(card_date,as_of_utc):return common.schedule('wnba',card_date,as_of_utc)

def build_context(events,as_of_utc,allow_stale=False,overrides_path=None):
    if overrides_path:raise ValueError('VERSIONED_PACKAGE_REQUIRED')
    return common.context('wnba',events,as_of_utc)

def forecast_event(event,context,simulations=100000):return forecast(event,context,simulations)
