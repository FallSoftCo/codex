import importlib.util,json,time
from pathlib import Path
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
Q=Path("/aosp/development/lax-three-context-20261018-r01/qualification")
sp=importlib.util.spec_from_file_location("m",Q/"run_goal_definition_r228.py");m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
C=m.ROOT/"goal-discovery-r234";p=json.loads((C/"protocol.json").read_text());a=p["actors"]["reporter"];b=p["actors"]["engineer"]
secret=json.loads((m.ROOT/"ordinary/installation-intent.json").read_text())
api=lambda path:m.request("http://127.0.0.1:18783",secret["credentials"]["Owner"]["token"],"GET",path)
d=api("deliveries/c86c02df-e05d-4325-8c86-befc3aed2d21")
q=api("attention/b367d4b0-b68b-5404-bd24-e92bc8984e7b")
import subprocess
env=dict(x.split("=",1) for x in json.loads(subprocess.check_output(["docker","inspect","--format","{{json .Config.Env}}","harness-postgres"],text=True)) if "=" in x)
dbc=json.loads(Path("/var/lib/harness-deployments/ozzz-native-20261019-r01/database.json").read_text());role=dbc["user"]
dbc.update(user=env["POSTGRES_USER"],password=env["POSTGRES_PASSWORD"],application_name="goal-discovery-failure-audit-r236")
with psycopg.connect(**dbc,row_factory=dict_row,autocommit=True) as db:
 db.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
 snap=m.snapshot(db,a,b)
 commands=db.execute("SELECT operation,result FROM hb_attention_command WHERE attention=%s",("b367d4b0-b68b-5404-bd24-e92bc8984e7b",)).fetchall()
intent=json.loads((C/"answer-b367d4b0-b68b-5404-bd24-e92bc8984e7b-intent.json").read_text())
continuation={"type":"hollywoodQuestionAnswer","attentionId":"b367d4b0-b68b-5404-bd24-e92bc8984e7b","answers":intent["payload"]["response"]["answers"]}
new_delivery_ids={x["id"] for x in snap["deliveries"] if x["event"] in ["b51b4645-1fec-4fd2-8812-5aa02e650c47","f45c7714-20ad-47fe-935c-dbc964cee068"]}
result={"at":time.time(),"original":d,"question":q,"admittedAnswerCommands":commands,"serializedRejectedAnswerBytes":len(json.dumps(continuation).encode()),"newDeliveries":[x for x in snap["deliveries"] if x["id"] in new_delivery_ids],"newWork":[x for x in snap["work"] if x["value"].get("inputId") in ["b51b4645-1fec-4fd2-8812-5aa02e650c47","f45c7714-20ad-47fe-935c-dbc964cee068"]],"contexts":snap["contexts"],"ownPids":{u:m.pid(u) for who in [a,b] for u in who["units"].values()},"policyArtifacts":[{"path":str(x),"sha256":m.digest(x)} for x in Path(b["workspace"]).glob("policy-weekly-*.json")],"interpretation":"Source-informed native discovery and actual native peer delegation observed. Full journey failed in coordinator's QA answer encoder: same2443-char facts duplicated into3 fields exceeded6000-byte continuation limit; no answer command admitted. Observer cleanup deliberately cancelled own original. Cancelled work will not be resumed or reported completed."}
m.saved(C/"failed-journey-audit-r236.json",m.h.serialize(result))
print(json.dumps({"original":d["delivery"]["state"],"answerCommands":len(commands),"answerBytes":result["serializedRejectedAnswerBytes"],"questionState":q["attention"]["state"],"activeTurns":sum(x["active_turn"] is not None for x in snap["contexts"]),"policyArtifacts":result["policyArtifacts"]}),flush=True)

