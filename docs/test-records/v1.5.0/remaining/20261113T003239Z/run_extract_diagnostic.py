import subprocess,json,sys
from pathlib import Path
r=Path(__file__).parent
script=(r/'diagnose-extract.py').read_text(encoding='utf8')
p=subprocess.Popen(['docker','exec','-i','astroagent-v15-backend-1','python','-u','-'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
p.stdin.write(script.encode('utf8'));p.stdin.close()
with (r/'extract-diagnostic.jsonl').open('w',encoding='utf8') as f:
 for raw in iter(p.stdout.readline,b''):
  line=raw.decode('utf8');f.write(line);f.flush()
  try:
   v=json.loads(line)
   if 'id' in v:print(v['id'],v.get('error','completed'),flush=True)
  except ValueError:pass
code=p.wait();(r/'extract-diagnostic-stderr.txt').write_bytes(p.stderr.read());sys.exit(code)
