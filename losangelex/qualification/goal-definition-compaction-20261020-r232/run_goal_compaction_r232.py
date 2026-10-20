"""One actual native-compaction continuation on our own completed QA actors."""
import hashlib,importlib.util,json,os,subprocess,time
from pathlib import Path
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
Q=Path("/aosp/development/lax-three-context-20261018-r01/qualification")
sp=importlib.util.spec_from_file_location("prior",Q/"run_goal_definition_r228.py")
m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
ROOT=m.ROOT;CASE=ROOT/"goal-definition-compaction-r232"
a=json.loads((ROOT/"definition/public.json").read_text());peer=json.loads((ROOT/"definition/peer/public.json").read_text())
private=json.loads((ROOT/"definition/installation-intent.json").read_text())
cfg=json.loads(Path(a["config"]).read_text());pcfg=json.loads(Path(peer["config"]).read_text())
protocol=json.loads((CASE/"protocol.json").read_text());configuration=json.loads((CASE/"native-config-intent.json").read_text())
api=lambda method,path,body=None:m.request("http://127.0.0.1:18783",private["credentials"]["Owner"]["token"],method,path,body)
def events(purpose,since):
 p=Path(cfg["state"])/purpose/"events.jsonl"
 if not p.exists():return []
 result=[]
 for line in p.read_text().splitlines():
  try:r=json.loads(line)
  except json.JSONDecodeError:continue
  if r.get("at",0)>=since:result.append(r)
 return result
def compactions(purpose,since):
 return [x for x in events(purpose,since) if x.get("event") in ["item/started","item/completed"] and x.get("item",{}).get("type")=="contextCompaction"]
def post(label,recipient,text):
 operation="goal-compaction-r232:"+label
 return m.submit(CASE,label,api,"POST","rooms/"+a["room"]+"/messages",
  {"operationId":operation,"kind":"request","audience":"room","recipientId":recipient,"body":text},"commands/"+operation)
def retire(db,state):
 snap=m.snapshot(db,a,peer)
 try:
  for d in snap["deliveries"]:
   if d["state"] not in ["completed","failed","cancelled","unknown"]:
    m.submit(CASE,"retire-"+str(d["id"]),api,"POST","deliveries/"+str(d["id"])+"/cancel",{},"deliveries/"+str(d["id"]))
  for who in [a,peer]:
   row=api("GET","placements/"+who["agent"])
   m.administrative_put(CASE,api,"placements/"+who["agent"],{"operationId":"goal-compaction-r232:retire:"+who["agent"],"hostId":who["host"],"revision":row["placement"]["revision"],"enabled":False})
 finally:
  units=[*a["units"].values(),*peer["units"].values(),*a["infrastructure"]]
  subprocess.run(["systemctl","stop",*units],check=True,capture_output=True)
  restored=[]
  for item in configuration["settings"]:
   p=Path(item["path"])
   if p.exists() and m.digest(p)==item["sha256"]:p.unlink();restored.append(str(p))
   else:restored.append({"path":str(p),"state":"changed-or-missing-not-overwritten"})
  m.saved(CASE/"retirement.json",{"at":time.time(),"state":state,"ownedUnitPids":{u:m.pid(u) for u in units},"nativeHomeConfigRestoration":restored,"originalHistoriesAndArtifactsRetained":True})
assert not (CASE/"execution-intent.json").exists(),"Reconcile original operation, do not repeat"
for n,digest in protocol["files"].items():assert m.digest(CASE/n)==digest,n
env=dict(x.split("=",1) for x in json.loads(subprocess.check_output(["docker","inspect","--format","{{json .Config.Env}}","harness-postgres"],text=True)) if "=" in x)
dbconfig=json.loads(Path("/var/lib/harness-deployments/ozzz-native-20261019-r01/database.json").read_text());role=dbconfig["user"]
dbconfig.update(user=env["POSTGRES_USER"],password=env["POSTGRES_PASSWORD"],application_name="goal-compaction-real-native-r232")
with psycopg.connect(**dbconfig,row_factory=dict_row,autocommit=True) as db:
 db.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
 histories=db.execute("SELECT agent,purpose,native_thread,active_turn FROM hb_purpose_context WHERE agent=ANY(%s::uuid[]) ORDER BY agent,purpose",([a["agent"],peer["agent"]],)).fetchall()
 assert len(histories)==6 and all(x["active_turn"] is None for x in histories)
 baseline={who["agent"]:m.h.usage(conf,"three") for who,conf in [(a,cfg),(peer,pcfg)]}
 m.saved(CASE/"execution-intent.json",m.h.serialize({"at":time.time(),"protocolSha256":m.digest(CASE/"protocol.json"),"runnerSha256":m.digest(__file__),"existingHistories":histories,"baselineUsage":baseline,"scope":"Explicit new finite continuation on our completed QA identities; no user-stopped owner/timer or original task replay."}))
 state="observation-window-ended";started=None;initial=None;late=None;engineer=None
 try:
  subprocess.run(["systemctl","start",*a["infrastructure"]],check=True,capture_output=True)
  for who in [a,peer]:
   row=api("GET","placements/"+who["agent"]);assert row["state"]=="paused"
   m.administrative_put(CASE,api,"placements/"+who["agent"],{"operationId":"goal-compaction-r232:enable:"+who["agent"],"hostId":who["host"],"revision":row["placement"]["revision"],"enabled":True})
  subprocess.run(["systemctl","start",*a["units"].values(),*peer["units"].values()],check=True,capture_output=True)
  deadline=time.time()+60
  while not (m.ready(cfg) and m.ready(pcfg)):
   if time.time()>deadline:raise RuntimeError("Same-history startup not ready; no human task submitted")
   time.sleep(.5)
  same=db.execute("SELECT agent,purpose,native_thread,active_turn FROM hb_purpose_context WHERE agent=ANY(%s::uuid[]) ORDER BY agent,purpose",([a["agent"],peer["agent"]],)).fetchall()
  assert {(str(x["agent"]),x["purpose"],x["native_thread"]) for x in same}=={(str(x["agent"]),x["purpose"],x["native_thread"]) for x in histories}
  started=time.time();initial=post("original",a["agent"],(CASE/"request.txt").read_text());original=initial["deliveries"][0]["id"]
  m.saved(CASE/"request-public.json",{"at":started,"originalDelivery":original,"originalEvent":initial["event"]["id"],"deadline":started+protocol["budgets"]["seconds"]})
  last=None;quiet=None;answered=False
  while time.time()<started+protocol["budgets"]["seconds"]:
   now=time.time();snap=m.snapshot(db,a,peer);reader=compactions("reader",started);writer=compactions("writer",started)
   comp_start=next((x for x in reader if x["event"]=="item/started"),None)
   if late is None and comp_start:
    item=comp_start["item"]["id"]
    assert not any(x["event"]=="item/completed" and x["item"]["id"]==item for x in reader),"Reader compaction already completed before exposure; no false in-flight claim"
    m.saved(CASE/"reader-compaction-exposure.json",comp_start)
    late=post("late-clarification",a["agent"],(CASE/"late-clarification.txt").read_text().replace("{originalEvent}",initial["event"]["id"]))
    engineer=post("engineer",peer["agent"],(CASE/"engineer-request.txt").read_text());continue
   pending=[x for x in snap["attention"] if str(x["agent"])==a["agent"] and x["state"]=="pending"]
   if pending and not answered:
    m.response(CASE,"participant-answer",api,pending[0],(CASE/"participant-answer.txt").read_text());answered=True;continue
   row=next(x for x in snap["deliveries"] if str(x["id"])==original)
   cu=m.h.usage(cfg,"three");pu=m.h.usage(pcfg,"three")
   delta=cu["total_tokens"]+pu["total_tokens"]-sum(x["total_tokens"] for x in baseline.values())
   summary={"at":now,"originalState":row["state"],"activeContexts":sum(x["active_turn"] is not None for x in snap["contexts"]),"readerCompactionEvents":len(reader),"writerCompactionEvents":len(writer),"inputDuringCompactionSubmitted":late is not None,"addedReportedTokens":delta}
   marker=json.dumps({k:v for k,v in summary.items() if k!="at"},sort_keys=True)
   if marker!=last:
    m.saved(CASE/"latest.json",m.h.serialize({"summary":summary,"snapshot":snap,"readerCompactions":reader,"writerCompactions":writer}))
    with (CASE/"observations.jsonl").open("a") as f:f.write(json.dumps(m.h.serialize({"summary":summary,"snapshot":snap}))+"\n")
    print(json.dumps(summary),flush=True);last=marker
   if late is None and now-started>protocol["budgets"]["compactionStartSeconds"]:state="required-reader-compaction-not-observed";break
   if delta>protocol["budgets"]["addedReportedNativeTokens"]:state="added-usage-budget-exceeded";break
   terminal=all(x["state"] in ["completed","cancelled","failed","unknown"] for x in snap["deliveries"])
   if terminal and not any(x["active_turn"] for x in snap["contexts"]):
    if quiet is None:quiet=now
    if now-quiet>=12:state="settled" if row["state"]=="completed" and late else "settled-with-incomplete-journey";break
   else:quiet=None
   time.sleep(1)
  snap=m.snapshot(db,a,peer)
  m.saved(CASE/"result.json",m.h.serialize({"at":time.time(),"state":state,"seconds":time.time()-started,
   "snapshot":snap,"readerCompactions":compactions("reader",started),"writerCompactions":compactions("writer",started),
   "originalDelivery":original,"originalEvent":initial["event"]["id"],"lateInput":late,"engineerRequest":engineer,
   "consumerUsage":m.h.usage(cfg,"three"),"producerUsage":m.h.usage(pcfg,"three"),"baselineUsage":baseline,
   "initialHistories":histories,"operatorArtifactRepairs":0,"scope":"Actual native automatic compaction and new input on persistent goal histories; artifacts independently audited next."}))
  print(json.dumps({"state":state,"originalDelivery":original,"seconds":time.time()-started,"readerCompactionEvents":len(compactions("reader",started)),"writerCompactionEvents":len(compactions("writer",started))}),flush=True)
 except BaseException as e:
  m.saved(CASE/"runner-failure.json",{"at":time.time(),"error":type(e).__name__,"detail":str(e)[:1000],"newTaskReplays":0,"action":"Retain original operations; no artifact repair."})
  raise
 finally:retire(db,state)
