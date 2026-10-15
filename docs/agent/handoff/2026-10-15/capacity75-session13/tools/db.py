import sys,json
sys.path.insert(0,'/workspaces/cp-cap13/scripts')
import generate_staging_state as state, psycopg
from psycopg.rows import dict_row
def connection(row_factory=dict_row):
    state.staging_environment()
    proxy=state.railway(f'query {{ tcpProxies(environmentId:"{state.ENVIRONMENT}", serviceId:"{state.POSTGRES}") {{ domain proxyPort applicationPort }} }}')['tcpProxies']
    assert len(proxy)==1 and proxy[0]['applicationPort']==5432
    v=state.command_json(['railway','variable','list','-p',state.PROJECT,'-e',state.ENVIRONMENT,'-s',state.POSTGRES,'--json'])
    try:
        return psycopg.connect(host=proxy[0]['domain'],port=proxy[0]['proxyPort'],user=v['PGUSER'],password=v['PGPASSWORD'],dbname=v['PGDATABASE'],connect_timeout=15,options='-c default_transaction_read_only=on -c statement_timeout=60000',row_factory=row_factory)
    finally: v.clear()
def engine():
    """SQLAlchemy engine over the same read-only, statement-timeout connection."""
    import sqlalchemy
    return sqlalchemy.create_engine('postgresql+psycopg://', creator=lambda: connection(row_factory=psycopg.rows.tuple_row), poolclass=sqlalchemy.pool.NullPool)
if __name__=='__main__':
    with connection() as db:
        for sql in sys.argv[1:]:
            print('##',sql[:120]); 
            for r in db.execute(sql).fetchall(): print(json.dumps(r,default=str))
