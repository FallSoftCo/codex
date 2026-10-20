"""Independent functional outcome checks; no model output repair."""
import csv, io, json, subprocess, sys, tempfile
from pathlib import Path

FIELDS=["learner_id","cohort","consented","practice_sessions","updated_at"]
POLICY={"revision":2,"minParticipants":10,"minPracticeSessions":6,"requiresAllConsent":True}

def rows_for(name,count,sessions=6,consent=True):
    return [{"learner_id":name+"-person-"+str(i),"cohort":name,"consented":"yes" if consent else "no",
             "practice_sessions":str(sessions),"updated_at":"2026-10-20T10:00:00Z"} for i in range(count)]

def sample_rows():
    rows=rows_for("north",10)+rows_for("river",10,5)+rows_for("studio",10)+rows_for("tiny",9)
    rows[20]["consented"]="no"
    # Later record occurs before the older record in file order.
    rows += [{"learner_id":"north-person-0","cohort":"north","consented":"no",
              "practice_sessions":"1","updated_at":"2026-10-19T10:00:00Z"}]
    return rows

def csv_text(rows):
    s=io.StringIO();w=csv.DictWriter(s,fieldnames=FIELDS);w.writeheader();w.writerows(rows);return s.getvalue()

def reference(rows,policy):
    latest={}
    for row in rows:
        key=(row["cohort"],row["learner_id"])
        if key not in latest or row["updated_at"]>latest[key]["updated_at"]:latest[key]=row
    cohorts=[]
    for name in sorted({r["cohort"] for r in latest.values()}):
        people=[r for r in latest.values() if r["cohort"]==name]
        consented=sum(r["consented"]=="yes" for r in people)
        eligible=(len(people)>=policy["minParticipants"] and
                  (not policy["requiresAllConsent"] or consented==len(people)) and
                  all(int(r["practice_sessions"])>=policy["minPracticeSessions"] for r in people))
        cohorts.append({"cohort":name,"learners":len(people),"consented":consented,"eligible":eligible})
    return {"ready":sum(c["eligible"] for c in cohorts),"cohorts":cohorts}

def evaluate(workspace):
    workspace=Path(workspace);checks=[]
    def check(name,passed,detail=None):
        checks.append({"name":name,"passed":bool(passed),"detail":detail})
    code=workspace/"intake_report.py"
    check("requested CLI exists",code.is_file())
    if not code.is_file():return checks
    cases=[("sample",sample_rows(),POLICY),("empty",[],POLICY),
           ("policy is data",rows_for("small",3,2),{**POLICY,"minParticipants":3,"minPracticeSessions":2}),
           ("latest revocation",rows_for("revoked",10)+[{"learner_id":"revoked-person-0","cohort":"revoked",
             "consented":"no","practice_sessions":"6","updated_at":"2026-10-21T10:00:00Z"}],POLICY)]
    with tempfile.TemporaryDirectory(prefix="goal-outcome-",dir=workspace) as t:
        t=Path(t)
        for name,rows,policy in cases:
            source=t/"input.csv";p=t/"policy.json";source.write_text(csv_text(rows));p.write_text(json.dumps(policy))
            original=source.read_bytes()
            try:
                result=subprocess.run([sys.executable,str(code),str(source),str(p)],capture_output=True,text=True,timeout=12,cwd=workspace)
                value=json.loads(result.stdout)
                check(name+" behavioral outcome",result.returncode==0 and value==reference(rows,policy),
                      {"exitCode":result.returncode,"observed":value,"expected":reference(rows,policy)})
                private=[r["learner_id"] for r in rows]
                check(name+" no learner identifiers",not any(x in result.stdout+result.stderr for x in private))
                check(name+" source retained",source.read_bytes()==original)
            except Exception as e:check(name+" executes",False,type(e).__name__)
        source=t/"input.csv";p=t/"policy.json";source.write_text(csv_text(list(reversed(sample_rows()))));p.write_text(json.dumps(POLICY))
        try:
            result=subprocess.run([sys.executable,str(code),str(source),str(p)],capture_output=True,text=True,timeout=12,cwd=workspace)
            check("record order independent",result.returncode==0 and json.loads(result.stdout)==reference(sample_rows(),POLICY))
        except Exception as e:check("record order independent",False,type(e).__name__)
        bad=rows_for("private-bad",1);bad[0]["practice_sessions"]="bad"
        source.write_text(csv_text(bad))
        try:
            result=subprocess.run([sys.executable,str(code),str(source),str(p)],capture_output=True,text=True,timeout=12,cwd=workspace)
            check("malformed input rejected without identifier leak",result.returncode!=0 and
                  "private-bad-person-0" not in result.stdout+result.stderr)
        except Exception as e:check("malformed input rejected without identifier leak",False,type(e).__name__)
    expected=reference(sample_rows(),POLICY)
    try:sample=json.loads((workspace/"sample-report.json").read_text())
    except Exception:sample=None
    check("delivered sample reflects final policy and human headline clarification",sample==expected,{"observed":sample,"expected":expected})
    check("README delivered",(workspace/"README.md").is_file())
    return checks
