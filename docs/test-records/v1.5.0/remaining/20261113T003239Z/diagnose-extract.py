import json,time
from astroagent.config import LocalSettings
from astroagent.local_model_client import LocalModelClient
from astroagent.errors import ServiceError
client=LocalModelClient(LocalSettings(proxy_token='0'*64))
original=client.request
last={}
def request(path,*args,**kwargs):
 result=original(path,*args,**kwargs)
 if path=='/api/chat':last['content']=result.get('message',{}).get('content')
 return result
client.request=request
for task in [{'id': '15', 'input': 'Gaia: RA 0 deg, Dec -89.5 deg, radius 0.1 deg', 'standard': '零坐标有效，负赤纬保留，半径单位deg', 'action': 'extract'}, {'id': '16', 'input': '查Gaia，RUWE<1.4，视差信噪比>=10，中心还没决定', 'standard': 'ruwe_max1.4 lt、parallax_snr_min10 gte；缺坐标半径', 'action': 'extract'}, {'id': '17', 'input': 'Gaia圆锥查询半径30角分，RUWE不超过1.2', 'standard': 'radius30arcmin、ruwe_max1.2 lte；缺中心', 'action': 'extract'}]:
 try:out,_=client.generate('extract',task['input'],'bullets');row={'id':task['id'],'output':out}
 except ServiceError as exc:row={'id':task['id'],'error':exc.error.code,'cause':str(exc.__cause__)}
 row['raw']=last.get('content');print(json.dumps(row,ensure_ascii=False),flush=True)
