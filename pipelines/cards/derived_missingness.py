"""Product-level receipt for research children that consume a previously computed forecast."""
from .missingness import seal_audit, verify_audit


def binding(row, league, event_id, model_id, products):
    return dict(league=league, event_id=event_id, model_id=model_id, products=products,
                forecast={k: v for k, v in row.items() if k != "missingness_audit"})


def attach(row, league, event_id, model_id, products, *, inputs, method, missing):
    kwargs = binding(row, league, event_id, model_id, products)
    row["missingness_audit"] = seal_audit(**kwargs, details={
        "method": method, "input_observations": inputs, "unresolved_inputs": missing,
        "change_attribution": {"sporting": None, "missingness_imputation": None,
                               "model_version": None, "simulation_variation": None,
                               "interactions": None, "status": "PAIRED_PARENT_AND_STUDY_REQUIRED"},
        "validation": "SCOPE_SPECIFIC_SOURCE_SUPPORT_AND_LIMITS_UNREVIEWED"})
    return row


def check(row, league, event_id, model_id, products):
    if not verify_audit(row.get("missingness_audit"), **binding(row, league, event_id, model_id, products)):
        raise ValueError("MISSINGNESS_CHILD_READBACK_FAILED")
