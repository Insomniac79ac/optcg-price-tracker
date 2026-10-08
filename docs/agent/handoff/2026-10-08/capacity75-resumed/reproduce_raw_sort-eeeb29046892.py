import sys,importlib.util
from pathlib import Path
ROOT=Path('/tmp/capacity75-storage-query-20261008')
sys.path[:0]=[str(ROOT/'services/api/tests'),str(ROOT/'services/api'),str(ROOT/'packages/opcg_source_identity/src'),str(ROOT/'scripts')]
import pytest
import test_raw_dictionary_storage_postgres as tests
from sqlalchemy import text
spec=importlib.util.spec_from_file_location('old_storage','/tmp/capacity75-native-4995007/services/api/app/services/raw_dictionary_storage.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
mp=pytest.MonkeyPatch();fixture=tests.database.__wrapped__(mp);engine=next(fixture)
try:
    tests.storage=old
    try:tests.test_body_reads_are_bounded_even_when_planner_sorts_history(engine)
    except AssertionError:
        with engine.connect() as connection:
            value=connection.execute(text('SELECT last_value+1 n FROM body_reads')).scalar()
        assert value>34
        print('Prior released query reproduced unbounded body evaluations:',value,'allowed<=34; localhost synthetic fixture only')
    else:raise RuntimeError('Regression did not reproduce old query')
finally:
    try:next(fixture)
    except StopIteration:pass
    mp.undo()
