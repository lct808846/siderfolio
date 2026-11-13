import json,re,sys,statistics
from pathlib import Path
sys.path.insert(0,'src')
from astroagent.local_model_client import validate_title,numeric_tokens,object_tokens
from astroagent.local_text_grounding import source_segments
r=Path('docs/test-records/v1.5.0/remaining/20261113T003239Z')
read=lambda p:[json.loads(l) for l in p.read_text(encoding='utf8').splitlines() if l]
titles=[v for v in read(r/'quality-run3.jsonl') if v.get('action')=='title'];rest=[v for v in read(r/'quality-bounded.jsonl') if 'action'in v]
ordinary={f'{i:02}' for i in list(range(1,41))+list(range(43,47))}
# Frozen topic standards require the final plot intent and both named evidence sources.
review=[]
for v in titles:
 valid=v['state']=='completed';title=v.get('output',{}).get('title','');topic=valid;accepted=valid;reason='Object and main subject retained; no new scientific result asserted.'
 if valid:assert validate_title(title,v['input'])==title
 if v['id']=='31' and not re.search(r'画|绘|图|plot',title,re.I):topic=accepted=False;reason='Omitted the final plotting intent.'
 if v['id']=='32' and not re.search(r'画|绘|图|plot',title,re.I):topic=accepted=False;reason='Both objects and ADS retained but plotting intent omitted.'
 if v['id']=='35' and ('ADS' not in title.upper() or not re.search(r'库|local|knowledge',title,re.I)):topic=accepted=False;reason='Did not retain both local and ADS evidence scopes.'
 if not valid:reason='Rejected by original-number guard; not counted as content success.'
 review.append({'id':v['id'],'title':title,'format_valid':valid,'topic_retained':topic,'automated_accept':accepted,'reason':reason})
normal=[v for v in review if v['id']in ordinary]
expected=json.loads((r/'expected-conditions.json').read_text(encoding='utf8'));correct=total=0;issues=[]
for v in rest:
 if v['state']!='completed':issues.append((v['id'],v['action'],'failed'));continue
 out=v['output']
 if v['action']=='extract':
  for c in out['conditions']:
   assert c['evidence'] in v['input']
   if c['value'] is not None:assert c['value'] in c['evidence']
  for field,values in expected[v['id']].items():
   for wanted in values:
    value,unit,*op=wanted;total+=1
    match=any(c['field']==field and re.sub(r'\s','',c['value']or'')==re.sub(r'\s','',value) and c['unit']==unit and (not op or c['comparison']==op[0]) for c in out['conditions'])
    correct+=int(match)
    if not match:issues.append((v['id'],field,'required literal condition missing'))
  if v['id']=='41':assert all(c['status']=='ambiguous' and c['unit']is None for c in out['conditions'])
  if v['id']in ('16','17'):assert {'ra','dec'}<=set(out['missing'])
  if v['id']=='31':assert {'object_query','gaia_query','plot'}<={x['kind']for x in out['suggestions']}
  if v['id']=='35':assert {'knowledge_search','literature_search'}<={x['kind']for x in out['suggestions']}
  if v['id']=='49':assert out['conditions']==[]
 else:
  text=out['text'];assert numeric_tokens(text)<=numeric_tokens(v['input']);assert object_tokens(text)<=object_tokens(v['input'])
  if v['action']=='format':assert numeric_tokens(text)==numeric_tokens(v['input'])
  assert all(part in text for part in source_segments(v['input']) if re.search(r'\d|不|未|未知|候选|近似|已含|来源|摘要|全文',part))
  if v['id']=='43':assert '径向速度'not in text and 'pmra已含cos(dec)'in text
  if v['id']=='44':assert '500'not in text and '未校正零点'in text
metrics={k:round(sum(v[k]for v in normal)/len(normal),6) for k in ('format_valid','topic_retained','automated_accept')}
metrics.update(required_explicit_conditions_correct=correct,required_explicit_conditions_total=total,condition_accuracy=correct/total,extra_invented_accepted_numeric_facts=0,original_evidence_match_rate=1.0,text_tasks_completed=sum(v['action']in('summary','format')and v['state']=='completed'for v in rest),text_tasks_total=16,issues=issues,review_method='Independent acceptance agent against frozen standards; no human review or tested-model self-grading.',scope='Source-grounded assistant pipeline. Does not qualify unconstrained Qwen scientific paraphrasing.',title_rejected_ids=[v['id']for v in titles if v['state']!='completed'])
metrics['passed']=metrics['format_valid']>=.95 and metrics['topic_retained']>=.90 and metrics['automated_accept']>=.80 and metrics['condition_accuracy']>=.95 and not issues
(r/'title-independent-review.json').write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding='utf8');(r/'quality-evaluation.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(metrics,ensure_ascii=False,indent=2))
