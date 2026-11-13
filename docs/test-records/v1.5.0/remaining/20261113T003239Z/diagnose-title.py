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
for task in [{'id': '07', 'input': 'Compare the identifiers of NGC 869 and NGC 884', 'standard': '两个NGC编号均为主题；不可暗示已确认双星团关系', 'action': 'title'}, {'id': '13', 'input': 'Query Gaia DR3 source_id 65225812899613312', 'standard': '长整数完整，不能科学计数法或四舍五入', 'action': 'title'}, {'id': '16', 'input': '查Gaia，RUWE<1.4，视差信噪比>=10，中心还没决定', 'standard': 'ruwe_max1.4 lt、parallax_snr_min10 gte；缺坐标半径', 'action': 'title'}, {'id': '22', 'input': 'Find ADS papers on binary clusters from 2020 to 2024', 'standard': '文献主题、两端年份；不得换成当前年份', 'action': 'title'}]:
 try:out,_=client.generate('title',task['input'],'bullets');row={'id':task['id'],'output':out}
 except ServiceError as exc:row={'id':task['id'],'error':exc.error.code,'cause':str(exc.__cause__)}
 row['raw']=last.get('content');print(json.dumps(row,ensure_ascii=False),flush=True)
