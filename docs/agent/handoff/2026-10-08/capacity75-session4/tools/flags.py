import sys,json,re
sys.path.insert(0,'/workspaces/cp-s4/staging/scripts')
import generate_staging_state as s
s.staging_environment()
SV={'snkrdunk-collector':'2d7ab69b-ec1f-4c66-8da1-9c8769a6d14a','yuyutei-collector-shard-0':'6e39e82e-f73c-4eae-930c-7bf4dc7f2d67','yuyutei-collector-shard-1':'8912a70e-0bc3-4e2f-89dd-8fab56af5acd','yuyutei-collector-shard-2':'0169974d-e181-4454-8a0d-65733a76cdb3','yuyutei-collector-shard-3':'5150aeb3-108b-40ef-8091-7c796edb299a','yuyutei-collector-shard-4-v2':'2f4b87da-369d-4b95-8341-0123e6c1c442','yuyutei-collector-shard-5':'9666f7cb-516b-4bdd-a4dc-10ded8276b2e','yuyutei-collector-shard-6':'54051b0c-359d-47ec-8dcb-32535350c35f','yuyutei-collector-shard-7':'0eb249e7-ba9f-4d39-bdd4-802c0a23f9f3','yuyutei-collector-shard-8':'f83b902e-f79c-49f4-a2f6-b13018be1926','optcg-price-tracker':'5290becf-6956-4c5c-ab16-01d865587e07'}
SAFE=re.compile(r'(RAW_|STORAGE|DICTIONARY|APP_ENV|BUDGET|PACING|CLAIM|SHARD|SOURCE_|DUE|WINDOW|REQUEST|CRON|PSA|DISCOVERY|YUYU|SNKR|LIMIT|MAX|INTERVAL|DELAY|CAP)')
SECRET=re.compile(r'(PASS|SECRET|TOKEN|KEY|URL|DSN|AUTH|COOKIE|CRED)')
out={}
for name,sid in SV.items():
    v=s.command_json(['railway','variable','list','-p',s.PROJECT,'-e',s.ENVIRONMENT,'-s',sid,'--json'])
    out[name]={k:val for k,val in sorted(v.items()) if SAFE.search(k) and not SECRET.search(k) and not k.startswith('RAILWAY_')}
    v.clear()
print(json.dumps(out,indent=1))
