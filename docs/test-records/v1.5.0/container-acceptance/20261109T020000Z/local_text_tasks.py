import json,time,uuid,urllib.request
base='http://127.0.0.1:5173/api/v1/local-assistant/jobs/'
out={}
for action,text in [('summary','这是一份合成测试：观测记录包含天区名称、观测日期和仪器名称。'),('format','合成记录：目标M45；观测日期2026年11月9日。'),('extract','查询 M45 附近 5 角分的 Gaia 数据。')]:
 start=time.monotonic(); task=base+str(uuid.uuid4())
 try:
  req=urllib.request.Request(task,data=json.dumps({'action':action,'text':text,'output_format':'bullets'},ensure_ascii=False).encode(),headers={'Content-Type':'application/json'},method='PUT')
  obj=json.load(urllib.request.urlopen(req,timeout=20))['task']
  while obj['state'] in ('queued','running') and time.monotonic()-start<150:
   time.sleep(2); obj=json.load(urllib.request.urlopen(task,timeout=20))['task']
  out[action]={'state':obj['state'],'output':obj.get('output'),'error':obj.get('error'),'seconds':round(time.monotonic()-start,2)}
 except Exception as e: out[action]={'state':'error','error':str(e),'seconds':round(time.monotonic()-start,2)}
 print(action,out[action]['state'],flush=True)
 open('docs/test-records/v1.5.0/container-acceptance/20261109T020000Z/local-text-tasks-retry.json','w',encoding='utf8').write(json.dumps(out,ensure_ascii=False,indent=2))
