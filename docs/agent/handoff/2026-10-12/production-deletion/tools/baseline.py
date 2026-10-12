"""READ-ONLY staging baseline for the production-environment deletion (restart, 2026-10-12).

No mutation: Railway GraphQL reads, `railway variable list` reads, TCP connects, a
default_transaction_read_only Postgres session, Redis AUTH+PING, GET /health.
usage: baseline.py <out.json>
"""
import hashlib, json, socket, sys, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parents[6]
sys.path[:0] = [str(ROOT / 'scripts')]
import generate_staging_state as state, deploy_staging_collectors as dsc, collector_variables as cv
import psycopg

COMMIT = 'a504e476d98ab49ad7773a0c8c6b71e9d927b125'
PROD_ENV = 'd84d1abf-04c5-4315-841c-1c8838ebec89'
REDIS = 'bdc84418-d934-47f3-bb84-2f03cb7d8f5b'
API_URL = 'https://optcg-price-tracker-staging.up.railway.app/health'
S8 = ROOT / 'docs/agent/handoff/2026-10-10/capacity75-session8/evidence/'
S11 = ROOT / 'docs/agent/handoff/2026-10-12/capacity75-session11/evidence/live-state-start.json'
fleet = json.loads((S8 / 'fleet-after-pr98.json').read_text())
pre = json.loads((S8 / 'fleet-preflight-A.json').read_text())
s11 = json.loads(S11.read_text())
P, E = state.PROJECT, state.ENVIRONMENT
out = {'observed_at': state.timestamp(), 'read_only': True, 'expected_collector_commit': COMMIT}


def tcp(host, port, timeout=8):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return 'OPEN'
    except OSError as e:
        return 'CLOSED (%s)' % type(e).__name__


# Project, environments, services
proj = state.railway(f'query {{ project(id:"{P}") {{ name environments {{ edges {{ node {{ id name }} }} }} '
                     'services { edges { node { id name } } } } }')['project']
out['project_name'] = proj['name']
out['environments'] = sorted((e['node']['name'], e['node']['id']) for e in proj['environments']['edges'])
out['production_env_present'] = any(i == PROD_ENV for _, i in out['environments'])
out['project_services'] = sorted((s['node']['name'], s['node']['id']) for s in proj['services']['edges'])

# Staging service instances
nodes = dsc.inspect()
out['staging_instances'] = {}
for name, n in sorted(nodes.items()):
    latest = n.get('latestDeployment') or {}
    active = [d.get('id') for d in (n.get('activeDeployments') or [])]
    out['staging_instances'][name] = {
        'service_id': n['serviceId'], 'latest': latest.get('id'), 'latest_status': latest.get('status'),
        'active': active, 'cron': n.get('cronSchedule'), 'replicas': n.get('numReplicas'),
        'start_sha256': hashlib.sha256((n.get('startCommand') or '').encode()).hexdigest()}

# Collectors: exact-commit marker, digest, cron/start/daily-v1 vs references
out['collectors'] = {}
for name in sorted(cv.delivery.NAMES):
    n = nodes[name]; latest = n.get('latestDeployment') or {}
    row = {'latest': latest.get('id'), 'status': latest.get('status')}
    try:
        d = dsc.read_deployment(latest['id'], n['serviceId'], COMMIT)
        row['marker'] = True; row['digest'] = cv.digest(d)
    except Exception as e:
        row['marker'] = False; row['error'] = str(e)
    ref = s11['services'][name]
    row['same_as_session11_start'] = (row['latest'], row.get('digest')) == (ref['latest'], ref['digest'])
    row['cron'] = n.get('cronSchedule'); row['cron_unchanged'] = row['cron'] == fleet['services'][name]['cron']
    row['start_command_unchanged'] = hashlib.sha256((n.get('startCommand') or '').encode()).hexdigest() == pre['services'][name]['start_command_sha256']
    v = cv.read_variables(n['serviceId'])
    row['daily_v1'] = {k: v.get(k) for k in ('RAW_DICTIONARY_STORAGE_ENABLED', 'RAW_DICTIONARY_STORAGE_MODE', 'APP_ENV')}
    row['vars_unchanged'] = row['daily_v1'] == fleet['services'][name]['variables']
    out['collectors'][name] = row
out['collectors_all_ok'] = all(r['marker'] and r['status'] == 'SUCCESS' and r['same_as_session11_start'] and r['cron_unchanged']
                               and r['start_command_unchanged'] and r['vars_unchanged'] and r['daily_v1']['RAW_DICTIONARY_STORAGE_MODE'] == 'daily-v1'
                               for r in out['collectors'].values())

# GitHub deploy triggers / auto-deploy on every staging service
out['triggers'] = {name: dsc.deploy_triggers(n['serviceId']) for name, n in sorted(nodes.items())}
out['collector_trigger_count'] = sum(len(out['triggers'][c]['triggers']) for c in cv.delivery.NAMES)
try:
    out['trigger_preflight'] = 'PASS' if dsc.refuse_github_triggers(nodes) else 'FAIL'
except Exception as e:
    out['trigger_preflight'] = 'REFUSED: %s' % e

# API health
try:
    with urllib.request.urlopen(API_URL, timeout=20) as r:
        out['api_health'] = {'status': r.status, 'body': json.loads(r.read())}
except Exception as e:
    out['api_health'] = {'error': repr(e)[:200]}


def proxies(env, svc):
    return [{k: p[k] for k in ('id', 'domain', 'proxyPort', 'applicationPort')} for p in
            state.railway(f'query {{ tcpProxies(environmentId:"{env}", serviceId:"{svc}") {{ id domain proxyPort applicationPort }} }}')['tcpProxies']]


# Staging Postgres (read-only session) and Redis (AUTH + PING)
out['staging_proxies'] = {'Postgres': proxies(E, state.POSTGRES), 'Redis': proxies(E, REDIS)}
pg = out['staging_proxies']['Postgres']
assert len(pg) == 1 and pg[0]['applicationPort'] == 5432
v = state.command_json(['railway', 'variable', 'list', '-p', P, '-e', E, '-s', state.POSTGRES, '--json'])
try:
    with psycopg.connect(host=pg[0]['domain'], port=pg[0]['proxyPort'], user=v['PGUSER'], password=v['PGPASSWORD'],
                         dbname=v['PGDATABASE'], connect_timeout=15,
                         options='-c default_transaction_read_only=on -c statement_timeout=30000') as db:
        out['postgres'] = {'port': pg[0]['proxyPort'],
                           'read_only': db.execute('show transaction_read_only').fetchone()[0],
                           'alembic': db.execute('select version_num from alembic_version').fetchone()[0],
                           'tables': db.execute("select count(*) from information_schema.tables where table_schema='public'").fetchone()[0],
                           'db_size': db.execute('select pg_size_pretty(pg_database_size(current_database()))').fetchone()[0]}
        db.rollback()
except Exception as e:
    out['postgres'] = {'error': repr(e)[:200]}
finally:
    v.clear()
rd = out['staging_proxies']['Redis']
v = state.command_json(['railway', 'variable', 'list', '-p', P, '-e', E, '-s', REDIS, '--json'])
try:
    import redis
    r = redis.Redis(host=rd[0]['domain'], port=rd[0]['proxyPort'], password=v.get('REDISPASSWORD') or v.get('REDIS_PASSWORD'),
                    socket_timeout=10, socket_connect_timeout=10)
    out['redis'] = {'port': rd[0]['proxyPort'], 'ping': r.ping()}
    r.close()
except Exception as e:
    out['redis'] = {'error': repr(e)[:200]}
finally:
    v.clear()

# Production proxies (as Railway reports them) and raw TCP state of the two ports
if out['production_env_present']:
    try:
        out['production_proxies'] = {'Postgres': proxies(PROD_ENV, state.POSTGRES), 'Redis': proxies(PROD_ENV, REDIS)}
    except Exception as e:
        out['production_proxies'] = {'error': str(e)}
out['production_ports'] = {'sakura.proxy.rlwy.net:21415': tcp('sakura.proxy.rlwy.net', 21415),
                           'tokaido.proxy.rlwy.net:48223': tcp('tokaido.proxy.rlwy.net', 48223)}
Path(sys.argv[1]).write_text(json.dumps(out, indent=1, default=str) + '\n')
print(json.dumps({k: out[k] for k in ('observed_at', 'environments', 'production_env_present', 'collectors_all_ok',
                                       'collector_trigger_count', 'trigger_preflight', 'api_health', 'postgres', 'redis',
                                       'staging_proxies', 'production_ports')} | {'production_proxies': out.get('production_proxies')}, indent=1, default=str))
