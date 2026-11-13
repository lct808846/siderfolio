import json,secrets,subprocess,time,uuid,os,sys
from pathlib import Path
root=Path(__file__).parent
name='astroagent-qa-'+uuid.uuid4().hex[:10]
password=secrets.token_hex(24)
def call(args): return subprocess.check_output(['docker',*args],text=True).strip()
image=call(['inspect','--format','{{.Image}}','astroagent-v15-postgres-1'])
created=False
try:
 call(['run','-d','--name',name,'--label','astroagent.acceptance.temporary='+name,'-e','POSTGRES_PASSWORD='+password,'-e','POSTGRES_DB=astroagent_test_maintenance','-p','127.0.0.1::5432',image]);created=True
 for _ in range(40):
  if subprocess.run(['docker','exec',name,'pg_isready','-U','postgres'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:break
  time.sleep(1)
 port=call(['port',name,'5432/tcp']).split(':')[-1]
 env=os.environ.copy();env['ASTROAGENT_RUN_POSTGRES_TESTS']='1';env['ASTROAGENT_RUN_LARGE_ACCEPTANCE']='1';env['ASTROAGENT_TEST_DATABASE_URL']=f'postgresql://postgres:{password}@127.0.0.1:{port}/astroagent_test_maintenance'
 with (root/'postgres-tests.txt').open('w',encoding='utf8') as log:
  rc=subprocess.run([sys.executable,'-m','pytest','-m','postgres','--basetemp=.astroagent/acceptance-tmp/'+name,'-q','-p','no:cacheprovider','--junitxml='+str(root/'postgres-tests.xml')],env=env,stdout=log,stderr=subprocess.STDOUT).returncode
 (root/'postgres-result.json').write_text(json.dumps({'exit_code':rc,'isolated_container':name,'daily_database_used':False}))
 print('isolated postgres tests exit',rc)
finally:
 if created:
  label=call(['inspect','--format','{{index .Config.Labels "astroagent.acceptance.temporary"}}',name])
  if label!=name:raise RuntimeError('cleanup label mismatch')
  call(['rm','-f','-v',name]);print('temporary postgres removed')
