"""Read-only: staging Postgres volume backups and schedules, newest first, with age.
usage: backups.py > out.json"""
import datetime, json, sys
sys.path[:0] = ['/workspaces/cp-s10/scripts']
import generate_staging_state as state
state.staging_environment()
P, E = state.PROJECT, state.ENVIRONMENT
assert E == '05d1eac2-510d-4bd3-999e-fea9ead766b7', 'not staging'
vols = state.railway(f'query {{ project(id:"{P}") {{ volumes {{ edges {{ node {{ name volumeInstances {{ edges {{ node {{ id environmentId serviceId currentSizeMB sizeMB }} }} }} }} }} }} }} }}')['project']['volumes']['edges']
now = datetime.datetime.now(datetime.timezone.utc)
out = {'observed_at': now.isoformat(), 'volumes': {}}
for v in vols:
    for vi in v['node']['volumeInstances']['edges']:
        vi = vi['node']
        if vi['environmentId'] != E or v['node']['name'] != 'postgres-volume':
            continue
        b = state.railway(f'query {{ volumeInstanceBackupList(volumeInstanceId:"{vi["id"]}") {{ id name createdAt expiresAt usedMB referencedMB }} }}')['volumeInstanceBackupList']
        s = state.railway(f'query {{ volumeInstanceBackupScheduleList(volumeInstanceId:"{vi["id"]}") {{ id name kind cron retentionSeconds }} }}')['volumeInstanceBackupScheduleList']
        b.sort(key=lambda x: x['createdAt'], reverse=True)
        for x in b:
            x['age_hours'] = round((now - datetime.datetime.fromisoformat(x['createdAt'].replace('Z', '+00:00'))).total_seconds() / 3600, 2)
        out['volumes'][v['node']['name']] = {'instance': vi['id'], 'current_mb': vi['currentSizeMB'], 'size_mb': vi['sizeMB'], 'schedules': s, 'backups': b}
pg = out['volumes']['postgres-volume']
out['newest'] = pg['backups'][0] if pg['backups'] else None
out['gate_backup_under_24h'] = bool(pg['backups']) and pg['backups'][0]['age_hours'] < 24
print(json.dumps(out, indent=1))
