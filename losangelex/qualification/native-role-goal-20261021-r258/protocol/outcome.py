import json,hashlib
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'))
def packet(raw,audience):
 value=json.loads(raw)
 assert type(value) is dict and value['schema']==1 and type(value['schema']) is int
 rows=[]
 for f in value['features']:
  assert type(f['version']) is int and f['version']>0
  if f['state']=='released':rows.append({k:f[k] for k in ['id','version','title']})
 return {'schema':1,'audience':audience,'sourceSha256':hashlib.sha256(raw).hexdigest(),'features':sorted(rows,key=lambda f:f['id'])}
def valid_packet(raw,got,audience):return canonical(got)==canonical(packet(raw,audience))
