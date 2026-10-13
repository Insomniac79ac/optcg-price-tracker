"""Read-only: hourly Postgres DISK_USAGE_GB series from Railway metrics. usage: volume_series.py <start-iso> [sample-seconds] > out.json"""
import json, sys
sys.path[:0] = ['/workspaces/cp-cap12/scripts']
import generate_staging_state as state
state.staging_environment()
P, E, S = state.PROJECT, state.ENVIRONMENT, state.POSTGRES
assert E == '05d1eac2-510d-4bd3-999e-fea9ead766b7'
q = state.railway(f'query {{ metrics(projectId:"{P}", environmentId:"{E}", serviceId:"{S}", measurements:[DISK_USAGE_GB], startDate:"{sys.argv[1]}", sampleRateSeconds:{int(sys.argv[2]) if len(sys.argv) > 2 else 3600}) {{ measurement values {{ ts value }} }} }}')
out = {'environment': 'staging', 'observed_at': state.timestamp(), 'measurements': {}}
for m in q['metrics']:
    out['measurements'][m['measurement']] = [{'ts': __import__('datetime').datetime.fromtimestamp(v['ts'], __import__('datetime').timezone.utc).isoformat(), 'value': v['value']} for v in m['values']]
print(json.dumps(out, indent=1))
