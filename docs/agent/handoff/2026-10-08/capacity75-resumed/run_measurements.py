import sys,runpy
from pathlib import Path
root=Path('/tmp/capacity75-resume-20261008')
sys.path[:0]=[str(root/'scripts'),str(root/'services/api'),str(root/'packages/opcg_source_identity/src')]
for name in ['coverage.py','measure.py','read_capacity_inputs.py','storage_projection.py']:
 print('READ',name,flush=True)
 runpy.run_path(str(Path(__file__).parent/name),run_name='__main__')
