import sys,json
sys.path.insert(0,'/workspaces/cp-s4/staging/scripts')
import generate_staging_state as s
s.staging_environment()
svc=sys.argv[1]; n=int(sys.argv[2]) if len(sys.argv)>2 else 6
q=f'''query {{ deployments(first:{n}, input:{{projectId:"{s.PROJECT}", environmentId:"{s.ENVIRONMENT}", serviceId:"{svc}"}}) {{ edges {{ node {{ id status createdAt updatedAt meta canRollback }} }} }} }}'''
d=s.railway(q)
for e in d['deployments']['edges']:
    n=e['node']; m=n.get('meta') or {}
    print(n['id'][:8],n['status'],n['createdAt'],n['updatedAt'],'commit=',(m.get('commitHash') or '')[:8],'branch=',m.get('branch'),'reason=',m.get('reason'),'by=',m.get('triggeredBy') or m.get('commitAuthor'),'msg=',(m.get('commitMessage') or '')[:50].replace('\n',' '))
