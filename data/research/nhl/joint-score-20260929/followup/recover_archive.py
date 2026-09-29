"""Restore exact frozen archive from a checkout of its immutable evidence commit."""
import argparse,hashlib,pathlib,zipfile
p=argparse.ArgumentParser();p.add_argument('--parts',type=pathlib.Path,required=True);p.add_argument('--destination',type=pathlib.Path,required=True);a=p.parse_args()
parts=sorted(a.parts.glob('evidence.zip.part*'))
if len(parts)!=45:raise SystemExit('EXPECTED_45_PARTS')
a.destination.mkdir(parents=True,exist_ok=False);target=a.destination/'original-evidence.zip'
with target.open('xb')as out:
 for f in parts:out.write(f.read_bytes())
expected='f8978a1772d8a8030b3a27ce3f5b5ecbdd63c5081010a12156e78257ad5d978c'
if hashlib.sha256(target.read_bytes()).hexdigest()!=expected:raise SystemExit('ARCHIVE_HASH_MISMATCH')
with zipfile.ZipFile(target)as z:
 for n in z.namelist():
  if pathlib.PurePosixPath(n).is_absolute()or '..'in pathlib.PurePosixPath(n).parts:raise SystemExit('UNSAFE_ARCHIVE_PATH')
 z.extractall(a.destination/'restored')
print('Verified and restored exact frozen evidence; no forecast or model values changed.')
