import base64, hashlib, json, os, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, quote
import requests
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

def now():
    return datetime.now(timezone.utc).isoformat()

def main():
    out = Path('novig_capture')
    out.mkdir(exist_ok=False)
    receipt = {'started_at_utc': now(), 'result': 'not_started', 'orders_submitted': 0, 'executable_quote_verified': False}
    code = 1
    try:
        host = os.environ['NOVIG_HOST'].rstrip('/')
        if host not in {'https://api.paper.novig.com', 'https://api.novig.com'}:
            raise ValueError('Host not allowlisted')
        receipt['host'] = host
        key_id = os.environ['NOVIG_KEY_ID']
        if not key_id:
            raise ValueError('Missing key ID')
        key = serialization.load_pem_private_key(Path(os.environ['NOVIG_PEM']).read_bytes(), password=None)
        path = '/v3/catalog/markets'
        query = urlencode(sorted({'league': os.environ.get('NOVIG_LEAGUE', 'NFL'), 'limit': '5'}.items()), quote_via=quote, safe='')
        ts = str(int(time.time() * 1000))
        message = '\n'.join(['NOVIG-V3', ts, 'GET', path, query, hashlib.sha256(b'').hexdigest()]).encode()
        if isinstance(key, ed25519.Ed25519PrivateKey):
            sig = key.sign(message)
        elif isinstance(key, ec.EllipticCurvePrivateKey) and isinstance(key.curve, ec.SECP256R1):
            sig = key.sign(message, ec.ECDSA(hashes.SHA256()))
        else:
            raise ValueError('Unsupported key type')
        headers = {'Novig-Key-Id': key_id, 'Novig-Timestamp': ts, 'Novig-Signature': base64.b64encode(sig).decode(), 'Accept': 'application/json', 'Content-Type': 'application/json'}
        receipt.update({'path': path, 'query': query, 'request_sent_at_utc': now()})
        with requests.Session() as session:
            response = session.get(host + path + '?' + query, headers=headers, timeout=(10, 30), allow_redirects=False)
        receipt.update({'response_received_at_utc': now(), 'http_status': response.status_code, 'response_sha256': hashlib.sha256(response.content).hexdigest()})
        (out / 'response.body').write_bytes(response.content)
        receipt['result'] = 'http_error'
        if response.status_code == 200:
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get('items'), list):
                raise ValueError('Unexpected catalog schema')
            receipt['catalog_items'] = len(payload['items'])
            receipt['result'] = 'catalog_success' if payload['items'] else 'catalog_success_empty'
            receipt['pagination_complete'] = False
            code = 0
    except Exception as exc:
        receipt['result'] = 'failed'
        receipt['error_type'] = type(exc).__name__
    finally:
        receipt['finished_at_utc'] = now()
        receipt['collector_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        receipt['commit_sha'] = os.environ.get('GITHUB_SHA')
        receipt['run_id'] = os.environ.get('GITHUB_RUN_ID')
        (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps(receipt, indent=2))
    return code

if __name__ == '__main__':
    raise SystemExit(main())
