"""Portable fitted linear/logistic/Poisson heads; no fitting during inference."""
import math
import numpy as np

def pack(pipeline,kind):
    imputer,scaler,head=pipeline.steps[0][1],pipeline.steps[1][1],pipeline.steps[2][1]
    return {'kind':kind,'impute':imputer.statistics_.tolist(),'mean':scaler.mean_.tolist(),'scale':scaler.scale_.tolist(),
        'coefficient':np.asarray(head.coef_).reshape(-1).tolist(),'intercept':float(np.asarray(head.intercept_).reshape(-1)[0])}

def predict(head,values):
    x=np.asarray([np.nan if v is None else v for v in values],dtype=float)
    if len(x)!=len(head['coefficient']) or np.isinf(x).any():raise ValueError('FEATURE_SCHEMA_OR_INFINITY')
    x=np.where(np.isnan(x),head['impute'],x)
    z=float(np.dot((x-np.asarray(head['mean']))/head['scale'],head['coefficient'])+head['intercept'])
    if head['kind']=='logistic':return float(1/(1+np.exp(-z)))
    if head['kind']=='poisson':return math.exp(z)
    if head['kind']=='linear':return z
    raise ValueError('UNKNOWN_FITTED_HEAD')
