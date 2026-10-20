"""Frozen real-model goal-definition pilot. Run once; reconcile accepted operations."""
import hashlib,importlib.util,json,subprocess,time,runpy
from pathlib import Path
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from lax_connector.host import request
from lax_connector.journal import saved
from lax_connector.purpose_install import activate
from lax_connector.collaboration_capture import administrative_put
Q=Path("/aosp/development/lax-three-context-20261018-r01/qualification")
ROOT=Path("/var/lib/lax-operating-model-comparison-20261020-r228");CASE=ROOT/"goal-definition-r228"
spec=importlib.util.spec_from_file_location("prior_helpers",Q/"run_human_input_comparison_r199.py")
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
digest=h.digest;pid=h.pid;submit=h.submit_once
protocol=json.loads((CASE/"protocol.json").read_text())
rubric=json.loads((CASE/"participant-review-rubric.json").read_text())

def snapshot(db,arm,peer):
    value=h.read_snapshot(db,arm)
    value["contexts"]=db.execute("SELECT agent,purpose,native_thread,active_turn FROM hb_purpose_context WHERE agent=ANY(%s::uuid[]) ORDER BY agent,purpose",([arm["agent"],peer["agent"]],)).fetchall()
    value["work"]=db.execute("SELECT id,agent,state,revision,value FROM hb_context_material WHERE kind='work' AND agent=ANY(%s::uuid[]) ORDER BY created_at",([arm["agent"],peer["agent"]],)).fetchall()
    value["attention"]=db.execute("SELECT id,agent,delivery,state,method,request,response_event FROM hb_attention WHERE authority=%s ORDER BY created_at",(arm["authority"],)).fetchall()
    return value

def ready(config):
    for purpose in ["reader","writer","responder"]:
        p=Path(config["state"])/("status-"+purpose+".json")
        if not p.is_file():return False
        d=json.loads(p.read_text());s=d["contexts"][purpose]
        if time.time()-d["at"]>=5 or s["active"] or s["held"] or not s["nativeThread"]:return False
    return True

def response(out,label,api,attention,text):
    receipt=api("GET","attention/"+str(attention["id"]))
    if not receipt["canRespond"]:raise RuntimeError("Original question no longer admits QA answer")
    answers={q["id"]:{"answers":[text]} for q in receipt["attention"]["request"]["questions"]}
    operation="goal-definition-r228:"+label
    body={"operationId":operation,"scope":receipt["scope"],"response":{"answers":answers}}
    return submit(out,label,api,"POST","attention/"+str(attention["id"])+"/response",body,
                  "attention/"+str(attention["id"])+"/commands/"+operation)

def retire(out,arm,peer,api,db,reason):
    units=[*arm["units"].values(),*peer["units"].values(),*arm["infrastructure"]]
    try:
        snap=snapshot(db,arm,peer)
        for d in snap["deliveries"]:
            if d["state"] not in ["completed","cancelled","failed","unknown"]:
                submit(out,"retire-"+str(d["id"]),api,"POST","deliveries/"+str(d["id"])+"/cancel",{},"deliveries/"+str(d["id"]))
        for who in [arm,peer]:
            row=api("GET","placements/"+who["agent"])
            administrative_put(out,api,"placements/"+who["agent"],{"operationId":"goal-definition-r228:retire:"+who["agent"],
              "hostId":who["host"],"revision":row["placement"]["revision"],"enabled":False})
    finally:
        subprocess.run(["systemctl","stop",*units],check=True,capture_output=True)
        saved(out/"retirement.json",{"at":time.time(),"reason":reason,"unitPids":{u:pid(u) for u in units},
          "originalHistoriesReceiptsAndArtifactsRetained":True,"unknownEffectsNotReplayed":True})

def run_arm(name,db):
    arm=json.loads((ROOT/name/"public.json").read_text());peer=json.loads((ROOT/name/"peer/public.json").read_text())
    setup=json.loads((ROOT/name/"installation-intent.json").read_text())
    cfg=json.loads(Path(arm["config"]).read_text());pcfg=json.loads(Path(peer["config"]).read_text())
    api=lambda method,path,body=None:request("http://127.0.0.1:18783",setup["credentials"]["Owner"]["token"],method,path,body)
    w=Path(arm["workspace"]);p=Path(peer["workspace"]);out=CASE/"runs"/name
    out.mkdir(parents=True,mode=0o700);(out/"administration").mkdir(mode=0o700)
    units=[*arm["units"].values(),*peer["units"].values()]
    assert all(pid(u)=="0" for u in units)
    fixed=json.loads((CASE/(name+"-fixed-inputs.json")).read_text())
    assert digest(w/"intake.csv")==fixed["intake.csv"]
    state="observation-window-ended"
    try:
        saved(out/"activation-intent.json",{"at":time.time(),"units":units,"models":"gpt-6.1-sol/xhigh","priorUsage":{"consumer":h.usage(cfg,"three"),"producer":h.usage(pcfg,"three")}})
        activate(arm["authority"],arm["agent"]);activate(peer["authority"],peer["agent"])
        limit=time.time()+60
        while not (all(int(pid(u))>1 for u in units) and ready(cfg) and ready(pcfg)):
            if time.time()>limit:raise RuntimeError("Fresh owned cohort not ready; inspect same state")
            time.sleep(.5)
        started=time.time()
        initial_body=(CASE/"common-request.txt").read_text()+"\n\n"+(CASE/(name+"-instructions.txt")).read_text()
        operation="goal-definition-r228:"+name+":original"
        initial=submit(out,"original",api,"POST","rooms/"+arm["room"]+"/messages",
          {"operationId":operation,"kind":"request","audience":"room","recipientId":arm["agent"],"body":initial_body},"commands/"+operation)
        original=initial["deliveries"][0]["id"]
        saved(out/"public.json",{"consumer":arm,"producer":peer,"originalEvent":initial["event"]["id"],
          "originalDelivery":original,"startedAt":started,"deadline":started+protocol["budgets"]["perArmSeconds"]})
        facts_at=None;peer_receipt=None;late_at=None;answered=set();rounds=0;reviews=[];last=None;quiet=None
        deadline=started+protocol["budgets"]["perArmSeconds"]
        while time.time()<deadline:
            now=time.time();snap=snapshot(db,arm,peer);cu=h.usage(cfg,"three");pu=h.usage(pcfg,"three")
            original_row=next(d for d in snap["deliveries"] if str(d["id"])==original)
            questions=[a for a in snap["attention"] if str(a["agent"])==arm["agent"] and a["state"]=="pending" and a["method"] in ["hollywood/question","item/tool/requestUserInput"] and str(a["id"]) not in answered]
            if questions:
                attention=questions[0];aid=str(attention["id"])
                if rounds>=protocol["budgets"]["maxParticipantAnswerRounds"]:
                    state="participant-answer-budget-exceeded";break
                if facts_at is None:
                    response(out,"participant-facts-"+aid,api,attention,(CASE/"participant-facts.txt").read_text())
                    facts_at=time.time();rounds+=1;answered.add(aid)
                    saved(out/"facts-exposure.json",{"at":facts_at,"nativeQuestion":aid,"mode":"native-question-answer"})
                    continue
                review_dir=out/"participant-reviews";review_dir.mkdir(mode=0o700,exist_ok=True)
                needed=review_dir/(aid+"-needed.json");decision=review_dir/(aid+"-decision.json")
                definition=w/"goal-definition.md"
                if not needed.exists():
                    proposal=definition.read_text() if definition.is_file() else None
                    saved(needed,{"at":now,"attention":h.serialize(attention),"definitionPath":str(definition),
                      "definitionSha256":digest(definition) if definition.is_file() else None,"definitionText":proposal,
                      "rubric":rubric["reviewBeforeApproval"],"expectedParticipantIntervention":True})
                    print(json.dumps({"arm":name,"participantReviewNeeded":str(needed),"decisionPath":str(decision)}),flush=True)
                if decision.exists():
                    d=json.loads(decision.read_text())
                    assert d["decision"] in ["approve","reject"] and d["reviewerKind"]=="coordinator-scripted-QA-participant"
                    assert len(d["rubric"])==len(rubric["reviewBeforeApproval"])
                    if d["decision"]=="approve":
                        assert all(x["satisfied"] for x in d["rubric"]) and definition.is_file()
                        assert d["definitionSha256"]==digest(definition),"Proposal changed after review; do not silently approve"
                    text=(CASE/("participant-approval.txt" if d["decision"]=="approve" else "participant-rejection.txt")).read_text()
                    if d["decision"]=="reject":
                        text+="\nRecorded missing or contradicted criteria:\n"+"\n".join(rubric["reviewBeforeApproval"][i] for i,x in enumerate(d["rubric"]) if not x["satisfied"])
                    elif definition.is_file():
                        (review_dir/(aid+"-reviewed-definition.md")).write_bytes(definition.read_bytes())
                        text+="\nReviewed goal-definition.md SHA256: "+d["definitionSha256"]+"."
                    response(out,"participant-review-"+aid,api,attention,text)
                    reviews.append({"attentionId":aid,"decision":d,"at":time.time()});rounds+=1;answered.add(aid)
                    continue
            if facts_at is None and name=="ordinary" and now-started>=60:
                operation="goal-definition-r228:"+name+":facts"
                receipt=submit(out,"participant-facts-fallback",api,"POST","rooms/"+arm["room"]+"/messages",
                  {"operationId":operation,"kind":"request","audience":"room","recipientId":arm["agent"],
                   "body":"Clarification to your original intake-report task:\n"+(CASE/"participant-facts.txt").read_text()},"commands/"+operation)
                facts_at=time.time();saved(out/"facts-exposure.json",{"at":facts_at,"mode":"predeclared60s-clarification-fallback","event":receipt["event"]["id"]});continue
            if facts_at is not None and peer_receipt is None:
                operation="goal-definition-r228:"+name+":engineer"
                peer_receipt=submit(out,"engineer",api,"POST","rooms/"+arm["room"]+"/messages",
                  {"operationId":operation,"kind":"request","audience":"room","recipientId":peer["agent"],
                   "body":(CASE/"producer-request.txt").read_text()},"commands/"+operation);continue
            writer_active=any(str(c["agent"])==arm["agent"] and c["purpose"]=="writer" and c["active_turn"] for c in snap["contexts"])
            if facts_at is not None and late_at is None and (w/"intake_report.py").is_file() and original_row["state"]=="running" and writer_active:
                saved(out/"inflight-exposure.json",{"at":now,"originalDelivery":h.serialize(original_row),"writerContexts":h.serialize(snap["contexts"]),"firstImplementationSha256":digest(w/"intake_report.py")})
                for label,filename in [("clarification","human-clarification.txt"),("status","human-status.txt")]:
                    operation="goal-definition-r228:"+name+":"+label
                    submit(out,label,api,"POST","rooms/"+arm["room"]+"/messages",
                      {"operationId":operation,"kind":"request","audience":"room","recipientId":arm["agent"],
                       "body":(CASE/filename).read_text()},"commands/"+operation)
                late_at=time.time();continue
            summary={"at":now,"originalDeliveryState":original_row["state"],"factsAdmitted":facts_at is not None,
              "peerStarted":peer_receipt is not None,"lateInputsAdmitted":late_at is not None,"participantAnswerRounds":rounds,
              "activeContexts":sum(c["active_turn"] is not None for c in snap["contexts"]),
              "consumerTokens":cu["total_tokens"],"producerTokens":pu["total_tokens"],
              "deliveries":{str(d["id"]):d["state"] for d in snap["deliveries"]}}
            marker=json.dumps({k:v for k,v in summary.items() if k!="at"},sort_keys=True)
            if marker!=last:
                saved(out/"latest.json",h.serialize({"summary":summary,"snapshot":snap,"consumerUsage":cu,"producerUsage":pu}))
                with (out/"observations.jsonl").open("a") as f:f.write(json.dumps(h.serialize({"summary":summary,"snapshot":snap}))+"\n")
                print(json.dumps({"arm":name,**{k:v for k,v in summary.items() if k!="deliveries"}}),flush=True);last=marker
            if cu["total_tokens"]+pu["total_tokens"]>protocol["budgets"]["totalReportedNativeTokensPerArmCeiling"]:
                state="native-reported-usage-budget-exceeded";break
            terminal=all(d["state"] in ["completed","cancelled","failed","unknown"] for d in snap["deliveries"])
            idle=not any(c["active_turn"] for c in snap["contexts"])
            if terminal and idle:
                if quiet is None:quiet=now
                if now-quiet>=12:
                    state="settled" if original_row["state"]=="completed" and facts_at and peer_receipt and late_at else "settled-with-incomplete-required-journey"
                    break
            else:quiet=None
            time.sleep(1)
        snap=snapshot(db,arm,peer)
        scores=runpy.run_path(str(CASE/"outcome_scorer.py"))["evaluate"](w)
        result={"at":time.time(),"arm":name,"state":state,"seconds":time.time()-started,
          "functionalChecks":scores,"snapshot":snap,"consumerUsage":h.usage(cfg,"three"),"producerUsage":h.usage(pcfg,"three"),
          "factsAt":facts_at,"lateInputsAt":late_at,"participantAnswerRounds":rounds,"proposalReviews":reviews,
          "sourceRetained":digest(w/"intake.csv")==fixed["intake.csv"],"explicitParticipantPolicy":True,
          "operatorImplementationRepairs":0,"scope":"One actual-model synthetic software workflow; qualitative review and comparison interpretation still required."}
        saved(out/"result.json",h.serialize(result))
        print(json.dumps({"arm":name,"state":state,"functionalChecksPassed":sum(c["passed"] for c in scores),"functionalChecksTotal":len(scores),"seconds":result["seconds"]}),flush=True)
        return h.serialize(result)
    except BaseException as error:
        saved(out/"runner-failure.json",{"at":time.time(),"error":type(error).__name__,"detail":str(error)[:1000],"action":"Retain original operations; no task replay or artifact repair."})
        raise
    finally:
        retire(out,arm,peer,api,db,state)

def main():
    assert not (CASE/"execution-intent.json").exists(),"Inspect original execution; no duplicate trial"
    for n,expected in protocol["files"].items():assert digest(CASE/n)==expected,n
    saved(CASE/"execution-intent.json",{"at":time.time(),"protocolSha256":digest(CASE/"protocol.json"),
       "runnerSha256":digest(__file__),"helperSha256":digest(Q/"run_human_input_comparison_r199.py"),
       "frozenFiles":protocol["files"],"arms":protocol["arms"],"models":"gpt-6.1-sol/xhigh"})
    env=dict(x.split("=",1) for x in json.loads(subprocess.check_output(["docker","inspect","--format","{{json .Config.Env}}","harness-postgres"],text=True)) if "=" in x)
    cfg=json.loads(Path("/var/lib/harness-deployments/ozzz-native-20261019-r01/database.json").read_text());role=cfg["user"]
    cfg.update(user=env["POSTGRES_USER"],password=env["POSTGRES_PASSWORD"],application_name="goal-definition-real-model-r228")
    outcomes={}
    with psycopg.connect(**cfg,row_factory=dict_row,autocommit=True) as db:
        db.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
        for name in protocol["arms"]:outcomes[name]=run_arm(name,db)
    saved(CASE/"paired-result.json",{"at":time.time(),"outcomes":outcomes,"claim":"Frozen pilot observations, no automatic superiority verdict."})

if __name__=="__main__":main()
