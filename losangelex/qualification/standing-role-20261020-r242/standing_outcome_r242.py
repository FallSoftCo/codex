"""Frozen deterministic outcome probes, distinct from actual-model behavior."""
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path

def expected(c):
 assert type(c) is dict and set(c)=={'schema','features'} and type(c['schema']) is int and c['schema']==1 and type(c['features']) is list
 seen=set();rows=[]
 for f in c['features']:
  assert type(f) is dict and set(f)=={'id','version','title','state'}
  assert type(f['id']) is str and f['id'].strip() and f['id'] not in seen
  assert type(f['version']) is int and f['version']>0
  assert type(f['title']) is str and f['title'].strip() and f['state'] in ('planned','released')
  seen.add(f['id'])
  if f['state']=='released':rows.append({k:f[k] for k in ['id','version','title']})
 return {'features':sorted(rows,key=lambda f:f['id'])}

def probe(program,cases):
 results=[]
 with tempfile.TemporaryDirectory(prefix='probe-',dir=program.parent) as d:
  path=Path(d)/'catalog.json'
  for i,c in enumerate(cases):
   raw=c if type(c) is str else json.dumps(c)
   path.write_text(raw);before=path.read_bytes()
   try:want=expected(json.loads(raw));valid=True
   except Exception:want=None;valid=False
   run=subprocess.run([sys.executable,str(program),str(path)],capture_output=True,text=True,timeout=15)
   try:got=json.loads(run.stdout)
   except Exception:got=None
   ok=(run.returncode==0 and got==want) if valid else (run.returncode!=0 and 'PRIVATE-CANARY' not in run.stdout+run.stderr)
   results.append({'case':i,'valid':valid,'passed':ok and path.read_bytes()==before,'exitCode':run.returncode,'actual':got,'expected':want})
 return results

def cases(protocol):
 valid=json.loads((protocol/'unseen-valid-cases.json').read_text())
 invalid=['{','[]',{'schema':1,'features':[{'id':'PRIVATE-CANARY','version':True,'title':'x','state':'released'}]},
 {'schema':True,'features':[]},
 {'schema':1,'features':[{'id':'x','version':1,'title':'x','state':'future'}]},
 {'schema':1,'features':[{'id':'x','version':1,'title':'x','state':'released'},{'id':'x','version':2,'title':'x','state':'planned'}]},
 {'schema':1,'features':[],'private':'PRIVATE-CANARY'}]
 return valid+invalid
