"""Resolve only a pre-model Reader/Responder failure with an acknowledged cut.

A failed native turn remains failed. This recognizes its diagnosed receipt so
ordinary pending material may be admitted afresh; it never retries that turn,
restores permissions, changes material or starts an inference.
"""
import asyncio,hashlib,json,os
from .automatic_refill_data import require
from .automatic_refill_history import _open,_prefix,recovered_installed,verify
from .journal import saved


def failure_proof(original, installed):
    owner, request = original["owner"], original["request"]
    require(owner["purpose"] in ("reader", "responder") and request["phase"] == "preTurn",
            "Only nonexecuting original pre-turn failure is supported")
    verify(original["originalHistory"], request, original["response"], installed)
    old = original["originalHistory"]
    stream, info = _open(old["path"])
    with stream:
        require((info.st_dev,info.st_ino)==(old["device"],old["inode"]),
                "Original native history identity changed")
        starts,last=0,None
        while stream.tell()<old["beforeBytes"]:
            line=stream.readline(min(8*1024**2+1,old["beforeBytes"]-stream.tell()))
            require(line.endswith(b"\n"),"Incomplete original native prefix")
            last=json.loads(line);body=last.get("payload",{})
            if last.get("type")=="event_msg" and body.get("type")=="task_started" and body.get("turn_id")==owner["turnId"]:
                starts+=1
        require(starts==1 and last.get("type")=="event_msg"
                and last.get("payload",{}).get("type")=="task_started"
                and last["payload"].get("turn_id")==owner["turnId"],
                "Original capture is not immediately after its unique turn start")
        stream.seek(installed["nativeHistoryBytes"])
        receipt=json.loads(stream.readline(8*1024**2+1))
        require(receipt.get("type")=="event_msg"
                and receipt.get("payload")=={"type":"context_window_refill_installed",**installed},
                "Original installed receipt boundary differs")
        input_id=None
        expected={"purpose":owner["purpose"],"materialIds":owner["materialIds"]}
        while stream.tell()<info.st_size:
            line=stream.readline(8*1024**2+1)
            require(line.endswith(b"\n") and len(line)<=8*1024**2,
                    "Incomplete or oversized original failure record")
            row=json.loads(line);body=row.get("payload",{})
            if row.get("type")=="response_item":
                require(input_id is None and body.get("type")=="function_call_output"
                        and body.get("name")=="context_material_available"
                        and body.get("internal_chat_message_metadata_passthrough",{}).get("turn_id")==owner["turnId"]
                        and json.loads(body.get("output",""))==expected,
                        "Original turn contains model output or another effect")
                input_id=body["id"]
            elif row.get("type")=="event_msg" and body.get("type")=="item_completed":
                item=body.get("item",{})
                require(input_id is not None and body.get("turn_id")==owner["turnId"]
                        and item.get("type")=="FunctionCallOutput" and item.get("id")==input_id
                        and item.get("name")=="context_material_available"
                        and json.loads(item.get("output",""))==expected,
                        "Original failed turn contains another completed item")
            else:
                require(row.get("type")=="event_msg" and body.get("type")=="task_complete"
                        and body.get("turn_id")==owner["turnId"]
                        and isinstance(body.get("error"),dict)
                        and "Original canonical refill is held" in body["error"].get("message",""),
                        "Original failure was not the diagnosed pre-model refill hold")
                end=stream.tell()
                require(_prefix(stream,old["beforeBytes"])==old["beforeSha256"]
                        and (os.fstat(stream.fileno()).st_dev,os.fstat(stream.fileno()).st_ino,
                             os.fstat(stream.fileno()).st_size)==(info.st_dev,info.st_ino,info.st_size),
                        "Original failure history changed")
                return {"failureHistoryBytes":end,"failureHistorySha256":_prefix(stream,end),
                        "phase":"preTurn","failedBeforeModel":True}
    raise RuntimeError("Original failed pre-model terminal evidence missing")


async def original_resolution(runner, wake):
    if runner.purpose not in ("reader","responder"):
        return False
    require(wake.get("state")=="finished" and wake.get("turn",{}).get("status")=="failed"
            and wake.get("nativeThread")==runner.thread,"Exact finished failed native wake required")
    matches=[]
    for path in runner.automatic.root.glob("*.json"):
        raw=path.read_bytes();j=json.loads(raw)
        if (j["owner"]["turnId"]==wake["nativeTurn"] and j["request"]["phase"]=="preTurn"
                and "response" in j):
            matches.append((path,raw,j))
    if not matches:return False
    require(len(matches)==1,"Original failed turn has ambiguous automatic checkpoints")
    path,raw,j=matches[0];owner=j["owner"]
    require(all(owner[k]==v for k,v in (("agentId",runner.config["agentId"]),
            ("contextId",runner.config["contextIds"][runner.purpose]),("purpose",runner.purpose),
            ("threadId",runner.thread))),"Original pre-model failure belongs to another purpose")
    installed=await asyncio.to_thread(recovered_installed,j["originalHistory"],j["request"]["operationId"])
    proof=await asyncio.to_thread(failure_proof,j,installed)
    operation="active-installed:"+hashlib.sha256(j["request"]["operationId"].encode()).hexdigest()
    receipt=await runner.agent.http(runner.purpose,"GET",
        f"agents/{runner.config['agentId']}/contexts/{runner.purpose}/operations/{operation}")
    require(receipt.get("schema")=="lax-active-context-installed/v1" and receipt.get("status")=="recorded"
            and receipt.get("operationId")==j["request"]["operationId"]
            and all(receipt.get("binding",{}).get(k)==v for k,v in (
                ("agentId",owner["agentId"]),("contextId",owner["contextId"]),("purpose",owner["purpose"]),
                ("nativeThread",owner["threadId"]),("nativeTurn",owner["turnId"]),("permitId",owner["permitId"]),
                ("materialIds",owner["materialIds"])))
            and all(receipt[k]==installed[k] for k in ("windowId","previousWindowId",
                "nativeHistoryBytes","nativeHistorySha256","snapshotSha256"))
            and path.read_bytes()==raw,"Original acknowledged failed pre-model cut differs")
    saved(runner.state/"original-refill-failure-resolution.json",{
        **proof,"nativeThread":runner.thread,"nativeTurn":wake["nativeTurn"],
        "disposition":"acknowledged_original_pre_model_refill_failure",
        "originalOperation":j["request"]["operationId"],"installationOperation":operation,
        "originalJournalSha256":hashlib.sha256(raw).hexdigest(),
        "originalTurnRepeated":False,"originalInputMarkedHandled":False,
        "newExecutionAdmitted":False,"modelTurnsStarted":0,"effectsReplayed":0})
    return True
