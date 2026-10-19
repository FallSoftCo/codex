"""One LAX identity with independent native reader, writer and responder contexts."""
import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import signal
import time
from pathlib import Path
from uuid import uuid4
from aiohttp import ClientSession, ClientTimeout
from .context_contract import COMMON, ROLES, ACTIONS, tools
from .activity import Activity
from .execution_scope import ExecutionScope
from .native_tool_session import NativeToolSession, definitions
from .native_tool_catalog import CAPABILITIES
from .context_observation import TERMINAL, original_turn, wait_terminal
from .journal import saved
from .native_goals import external_admission
from .native_policy import verify
from .rpc import AppServer

class ContextRunner:
    def __init__(self, agent, purpose):
        self.agent,self.purpose=agent,purpose
        self.config=agent.config
        self.state=agent.state/purpose
        self.state.mkdir(mode=0o700,exist_ok=True)
        self.thread=None
        self.turn=None
        self.finished=None
        self.admitted=asyncio.Event()
        self.active=False
        self.accepting=False
        self.closing=False
        self.effect_lock=asyncio.Lock()
        self.task=None
        self.failed=False
        self.execution_scope=None
        self.permit=None
        self.native_tools=None
        self.native_items={}
        self.executor=None
        self.early_activity=[]
        self.activity=Activity(state=self.state,scope=lambda:self.execution_scope,
            send=self.send_activity,secrets=tuple(self.config["tokens"].values())) if purpose=="writer" else None
        self.declarations=tools(purpose) + (definitions(self.config.get("installedPurposeRuntime",False)) if purpose=="writer" else [])
        self.allowed={t["name"] for t in self.declarations}
        self.rpc=AppServer(self.config["binary"],Path(self.config["homes"][purpose]),
          self.state/"native",self.event,self.tool,on_submission=self.submitted,enterprise=True,
          collaboration_channel=self.config.get("nativeCollaborationChannel") if purpose=="writer" else None,
          isolated_process_group=True)

    def trace(self,event,value):
        with (self.state/"events.jsonl").open("a") as f:
            f.write(json.dumps({"at":time.time(),"event":event,**value},default=str)+"\n")

    async def request(self,action,value=None,operation=None,turn=None):
        operation=operation or str(uuid4())
        payload={"operationId":operation,"action":action,"nativeThread":self.thread,
                 "nativeTurn":turn or self.turn or "runtime","value":value or {}}
        path=f"agents/{self.config['agentId']}/contexts/{self.purpose}"
        if action in ("pending", "ready"):
            return await self.agent.http(self.purpose,"POST",path,payload)
        journal=self.state/("operation-"+hashlib.sha256(operation.encode()).hexdigest()+".json")
        old=json.loads(journal.read_text()) if journal.exists() else None
        if old:
            if old["request"]!=payload:
                raise RuntimeError("Original context operation changed")
            if old.get("receipt") is not None:
                return old["receipt"]
        if old and old.get("state")!="rejected":
            # An uncertain original is observed, never submitted a second time.
            result=await self.agent.http(self.purpose,"GET",path+"/operations/"+operation)
        else:
            saved(journal,{"request":payload,"state":"intent"})
            try:
                result=await self.agent.http(self.purpose,"POST",path,payload)
            except Exception as error:
                from .errors import HttpFailure
                if isinstance(error,HttpFailure) and error.status in (400,403,409):
                    saved(journal,{"request":payload,"state":"rejected","status":error.status,
                                   "error":str(error)})
                    raise
                result=await self.agent.http(self.purpose,"GET",path+"/operations/"+operation)
        if (action=="admit" and result.get("delivery") is None
                or action=="reserve" and result["permit"]["state"]=="queued"):
            journal.unlink()
            return result
        saved(journal,{"request":payload,"state":"accepted","receipt":result})
        return result

    async def send_activity(self, record):
        scope=record["executionScope"]
        if (scope["agentId"]!=self.config["agentId"] or scope["purpose"]!=self.purpose
            or scope["contextId"]!=self.config["contextIds"][self.purpose]
            or scope["nativeThread"]!=self.thread):
            raise RuntimeError("Activity outbox belongs to another purpose context")
        frame=record["payload"]
        key=hashlib.sha256(json.dumps([scope["id"],frame["nativeTurn"],
            frame["itemId"],frame["phase"]]).encode()).hexdigest()
        payload={"operationId":"activity:"+key,"action":"activity",
            "nativeThread":scope["nativeThread"],"nativeTurn":scope["nativeTurn"],
            "value":{"scopeId":scope["id"],"payload":frame}}
        # Immutable log replay only. This endpoint cannot execute work or models.
        return await self.agent.http(self.purpose,"POST",
            f"agents/{self.config['agentId']}/contexts/{self.purpose}",payload)

    async def start(self):
        await self.rpc.start()
        await external_admission(self.rpc,False)
        # Code-mode models reach the filtered inner tools through exec/wait.
        # These wrappers confer no access to tools excluded by the native ceiling.
        allowed=[{"name":name} for name in sorted(self.allowed | {"exec","wait"})]
        if self.purpose=="writer":
            allowed += [{"name":name} for name in ("exec_command","write_stdin","apply_patch","update_plan")]
            if self.config.get("nativeCollaborationChannel"):
                allowed += [{"name":name} for name in ("coordination_act","collaborative_edit_plan")]
        settings={"cwd":self.config["workspace"],"model":self.config["model"],
          "sandbox":self.config.get("sandbox","danger-full-access"),
          "approvalPolicy":self.config.get("approvalPolicy","never"),
          "baseInstructions":COMMON+ROLES[self.purpose],
          "developerInstructions":"",
          "dynamicTools":self.declarations,"toolPolicy":{"allowedTools":allowed},
          "config":{"features.goal_external_admission":True,
            "features.goal_external_lifecycle":False,"agents.enabled":False,
            "features.multi_agent":False,"features.multi_agent_v2":False,
            "tools.update_plan.enabled":self.purpose=="writer",
            "model_reasoning_effort":self.config["effort"]}}
        record=self.state/"context.json"
        if record.exists():
            old=json.loads(record.read_text())
            if not old.get("nativeThread"):
                raise RuntimeError("Original thread creation uncertain; inspect before replacement")
            self.thread=old["nativeThread"]
            result=await self.rpc.call("thread/resume",{
              **settings,"threadId":self.thread,"excludeTurns":True})
        else:
            saved(record,{"state":"creating","contextId":self.config["contextIds"][self.purpose]})
            result=await self.rpc.call("thread/start",settings)
            self.thread=result["thread"]["id"]
            saved(record,{"state":"bound","contextId":self.config["contextIds"][self.purpose],
                          "nativeThread":self.thread,"purpose":self.purpose})
        # Upstream stages a never-used thread lazily. Metadata mutation explicitly
        # materializes its rollout without inventing input or running a model.
        await self.rpc.call("thread/name/set",{
            "threadId":self.thread,"name":self.config["agentId"]+":"+self.purpose})
        saved(record,{"state":"bound","contextId":self.config["contextIds"][self.purpose],
                      "nativeThread":self.thread,"purpose":self.purpose,"materialized":True})
        verify(settings["toolPolicy"],result)
        effective={(x.get("namespace") or "functions",x["name"])
                   for x in result["toolPolicy"]["allowedTools"]}
        if not {("functions",x) for x in self.allowed | {"exec","wait"}} <= effective:
            raise RuntimeError("Native policy hides a required purpose tool or code-mode wrapper")
        binding=await self.request("bind",{"runtimeProtocol":"lax-purpose-runtime/v3"},
            operation="bind:"+self.config["contextIds"][self.purpose]+":"+self.thread+":runtime-v3-work-updates-v1",turn="bootstrap")
        if binding.get("runtimeProtocol")!="lax-purpose-runtime/v3":
            raise RuntimeError("Hollywood native work/inference admission protocol unavailable")
        if self.purpose=="reader" and binding.get("workUpdates")!=1:
            raise RuntimeError("Hollywood native work-update contract unavailable")
        self.trace("context_started",{"threadId":self.thread,"tools":sorted(self.allowed),
                                    "effectiveToolPolicy":result.get("toolPolicy")})
        if self.activity:
            self.activity.start()
        # Resume changes metadata only. An unresolved original is observed,
        # never converted into another model submission.
        wake=self.state/"wake.json"
        old=json.loads(wake.read_text()) if wake.exists() else {}
        if old.get("state") in ("submission_intent","running","unknown"):
            self.turn=old.get("nativeTurn")
            self.permit=old.get("permitId")
            if not self.turn:
                self.failed=True
                self.trace("recovery_held",{"reason":"Original submission identity unavailable"})
            else:
                observed=await original_turn(self,self.turn)
                saved(self.state/"recovery-observation.json",{
                    "originalWake":old,"nativeTurn":self.turn,"turn":observed,"modelTurnsStarted":0})
                if observed["status"] in TERMINAL:
                    await self.request("end",{"status":observed["status"],**({"permitId":self.permit} if self.permit else {})},
                                       operation="context-end:"+self.turn)
                    saved(wake,{**old,"state":"finished","turn":observed,"recovered":True})
                else:
                    self.failed=True
                    self.trace("recovery_held",{"nativeTurn":self.turn,"status":observed["status"]})

    async def submitted(self,method,params,success):
        if self.native_tools:
            await self.native_tools.attention.submitted(method,params,success)

    async def event(self,method,params):
        if params.get("threadId") not in (None,self.thread):
            return
        self.trace(method,params)
        if method in ("item/started","item/completed") and isinstance(params.get("item"),dict):
            self.native_items[params["item"]["id"]]=params["item"]
        if method=="turn/started" and self.active and self.turn is None:
            self.turn=params["turn"]["id"]
            old=json.loads((self.state/"wake.json").read_text())
            saved(self.state/"wake.json",{**old,"nativeTurn":self.turn})
        if self.activity and self.active and method in ("item/started","item/completed","turn/plan/updated"):
            if self.execution_scope is None:
                if len(self.early_activity)>=1024:
                    raise RuntimeError("Unbound native activity exceeded bounded admission buffer")
                self.early_activity.append((method,params))
            else:
                self.activity.record(method,params)
        if method=="turn/completed" and self.finished and not self.finished.done():
            if self.turn and params["turn"]["id"]!=self.turn:
                return
            self.finished.set_result(params["turn"])
        if method=="hollywood/runtimeLost" and self.active:
            self.accepting=False
            self.agent.stop.set()
            if self.finished and not self.finished.done():
                self.finished.set_exception(RuntimeError("Original native connection lost; no automatic replay"))

    async def tool(self,method,params):
        await self.admitted.wait()
        async with self.effect_lock:
            if (not self.active or not self.accepting or self.closing
                or params.get("threadId",self.thread)!=self.thread
                or params.get("turnId",self.turn)!=self.turn):
                raise PermissionError("Original native turn no longer admits this callback")
            if method!="item/tool/call":
                from .attention import QUESTION,APPROVAL
                if self.native_tools and method in QUESTION+APPROVAL:
                    return await self.native_tools.call(method,params)
                raise PermissionError("Unsupported original native callback")
            name=params["tool"]
            if name not in self.allowed:
                raise PermissionError("Tool belongs to another context purpose")
            if name not in ACTIONS:
                if self.native_tools is None:
                    raise PermissionError("Original native tool session unavailable")
                return await self.native_tools.call(method, params)
            arguments=params["arguments"]
            if isinstance(arguments,str):
                arguments=json.loads(arguments)
            operation="context-tool:"+hashlib.sha256((self.thread+params["callId"]).encode()).hexdigest()
            try:
                result=await self.request(ACTIONS[name],arguments,operation=operation)
                self.trace("tool_receipt",{"tool":name,"operation":operation,"result":result})
                return {"success":True,"contentItems":[{"type":"inputText","text":json.dumps(result)}]}
            except Exception as error:
                self.trace("tool_error",{"tool":name,"error":str(error)})
                return {"success":False,"contentItems":[{"type":"inputText","text":json.dumps({
                    "error":str(error),"originalOperationId":operation,
                    "instruction":"Inspect current material; uncertain operations require original receipt reconciliation."})}]}

    async def settle_turn(self, fingerprint, turn):
        if turn.get("id")!=self.turn or turn.get("status") not in TERMINAL:
            raise RuntimeError("Original terminal native identity is unconfirmed")
        self.accepting=False
        async with self.effect_lock:
            await self.request("end",{"status":turn["status"],"permitId":self.permit},
                               operation="context-end:"+self.turn)
        saved(self.state/("turn-"+self.turn+".json"),{"fingerprint":fingerprint,
            "nativeThread":self.thread,"nativeTurn":self.turn,"turn":turn})
        saved(self.state/"wake.json",{"fingerprint":fingerprint,"state":"finished",
            "nativeThread":self.thread,"nativeTurn":self.turn,"turn":turn})

    async def run(self,fingerprint,pending):
        self.active=True
        self.executor=None
        self.turn=None
        self.permit=None
        self.execution_scope=None
        self.early_activity=[]
        self.accepting=False
        self.closing=False
        self.admitted.clear()
        self.finished=asyncio.get_running_loop().create_future()
        if self.purpose=="writer":
            identity=pending[0]["id"]
            try:
                accepted=await self.request("admit",{"workId":identity,"capabilities":CAPABILITIES},
                    operation="context-admit:"+identity,turn="admission")
                if accepted.get("delivery") is not None:
                    # A cached original acceptance is not current authorization.
                    # This read checks placement, role, room, cancellation and owner
                    # again without creating another claim or model submission.
                    accepted=await self.request("ready",{"workId":identity},turn="admission")
            except BaseException:
                self.failed=True
                self.active=False
                raise
            if accepted.get("delivery") is None:
                self.active=False
                saved(self.state/"admission-wait.json",accepted)
                return
            saved(self.state/"work-admission.json",accepted)
            if self.config.get("installedPurposeRuntime"):
                from .execution_lifecycle import ExecutionLifecycle
                self.executor=ExecutionLifecycle(accepted,config=self.config,
                    transport=lambda method,path,payload=None:self.agent.http(self.purpose,method,path,payload),
                    journal_directory=self.state/"executor")
                await self.executor.capture_resident(self.rpc)
        material_ids=[r["id"] for r in pending]
        try:
            reserved=await self.request("reserve",{"materialIds":material_ids},
                operation="context-reserve:"+fingerprint,turn="admission")
            if reserved["permit"]["state"]=="queued":
                self.active=False
                saved(self.state/"capacity-wait.json",reserved)
                return
            if reserved["permit"]["state"]!="reserved":
                raise RuntimeError("Original inference permit no longer admits submission")
            self.permit=reserved["permit"]["id"]
        except BaseException:
            self.failed=True
            self.active=False
            raise
        saved(self.state/"wake.json",{"fingerprint":fingerprint,"state":"submission_intent",
                                      "pending":pending,"nativeThread":self.thread,"permitId":self.permit})
        self.trace("wake",{"fingerprint":fingerprint,"pending":pending})
        try:
            if self.executor:
                await self.executor.require_live()
            result=await self.rpc.call("turn/start",{
              "threadId":self.thread,"input":[],"model":self.config["model"],
              "effort":self.config["effort"],"turnTrigger":"hollywood_context_material",
              "toolOutput":{"name":"context_material_available",
                "output":json.dumps({"purpose":self.purpose,"materialIds":[r["id"] for r in pending]}),
                "retain":False}})
            self.turn=result["turn"]["id"]
            material_ids=[r["id"] for r in pending]
            admission=await self.request("begin",{"materialIds":material_ids,"permitId":self.permit},
                               operation="context-begin:"+self.turn)
            if self.activity:
                self.execution_scope=ExecutionScope.accepted(admission,agent=self.config["agentId"],
                    thread=self.thread,turn=self.turn,materials=material_ids)
                saved(self.state/("execution-"+self.turn+".json"),admission)
                scope=self.execution_scope.as_dict()
                accepted=await self.agent.http(self.purpose,"GET","deliveries/"+scope["deliveryId"])
                role=await self.agent.http(self.purpose,"GET",
                    "connector/deliveries/"+scope["deliveryId"]+"/context")
                self.native_tools=NativeToolSession(accepted=accepted,scope=scope,
                    config=self.config,state=self.state/"native-tools",rpc=self.rpc,role=role,
                    transport=lambda method,path,payload,**kw: self.agent.http(self.purpose,method,path,payload,**kw),
                    finished=self.finished,native_items=self.native_items)
                if self.config.get("nativeCollaborationChannel"):
                    await self.native_tools.briefing()
                for method,params in self.early_activity:
                    self.activity.record(method,params)
                self.early_activity=[]
            self.accepting=True
            self.admitted.set()
            saved(self.state/"wake.json",{"fingerprint":fingerprint,"state":"running",
                                         "nativeThread":self.thread,"nativeTurn":self.turn,"permitId":self.permit})
            turn=await wait_terminal(self)
            await self.settle_turn(fingerprint,turn)
        except BaseException as error:
            self.accepting=False
            self.failed=True
            if self.turn and (not self.finished or not self.finished.done()):
                try:
                    await self.cancel()
                except Exception as cleanup:
                    self.trace("interrupt_unconfirmed",{"error":str(cleanup),"nativeTurn":self.turn})
                    self.agent.stop.set()
            settled=False
            if self.turn and self.finished and not self.finished.cancelled():
                try:
                    # Interrupt replies may precede turn/completed by a few ms.
                    # Observe that exact future; do not infer terminality or start a turn.
                    turn=await asyncio.wait_for(asyncio.shield(self.finished),5)
                    await self.settle_turn(fingerprint,turn)
                    self.trace("shutdown_terminal_settled",{"nativeTurn":self.turn,
                        "status":turn["status"],"workCompletionInferred":False})
                    settled=True
                except (Exception,asyncio.CancelledError) as observation:
                    self.trace("shutdown_terminal_unconfirmed",{"nativeTurn":self.turn,
                        "error":type(observation).__name__})
            if not settled:
                saved(self.state/"wake.json",{"fingerprint":fingerprint,"state":"unknown",
                         "nativeThread":self.thread,"nativeTurn":self.turn,"permitId":self.permit,"error":str(error)})
            raise
        finally:
            self.admitted.set()
            self.active=False

    async def cancel(self):
        if not self.active or not self.turn or self.closing:
            return
        self.closing=True
        self.accepting=False
        async with self.effect_lock:
            try:
                await self.request("close",operation="context-close:"+self.turn)
            finally:
                await self.rpc.call("turn/interrupt",{"threadId":self.thread,"turnId":self.turn},timeout=15)
        self.trace("interrupt",{"nativeTurn":self.turn})


class ContextAgent:
    def __init__(self,config,*,purpose=None):
        if purpose is not None and purpose not in ROLES:
            raise ValueError("Unknown native context purpose")
        self.config=config
        self.purpose=purpose
        self.state=Path(config["state"])
        self.state.mkdir(mode=0o700,exist_ok=True)
        self.lock=(self.state/"agent.lock").open("a")
        self.purpose_lock=None
        try:
            # Separate purpose services coexist. The all-context launcher is
            # exclusive with every purpose service, including during recovery.
            kind=fcntl.LOCK_EX if purpose is None else fcntl.LOCK_SH
            fcntl.flock(self.lock.fileno(),kind|fcntl.LOCK_NB)
            if purpose is not None:
                directory=self.state/purpose
                directory.mkdir(mode=0o700,exist_ok=True)
                self.purpose_lock=(directory/"runner.lock").open("a")
                fcntl.flock(self.purpose_lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.runners={p:ContextRunner(self,p) for p in ([purpose] if purpose else ROLES)}
        except BaseException:
            self.release_locks()
            raise
        self.status_path=self.state/("status-"+purpose+".json" if purpose else "status.json")
        self.reconcile_path=self.state/("reconcile-only-"+purpose+".json" if purpose else "reconcile-only.json")
        self.session=None
        self.stop=asyncio.Event()

    def release_locks(self):
        if self.purpose_lock:
            self.purpose_lock.close()
        self.lock.close()

    async def http(self,purpose,method,path,payload=None,*,native_source=None):
        # Transport version is not part of an immutable semantic operation.
        # Old effect/activity receipts keep their exact original fingerprints.
        if method=="POST" and path==f"agents/{self.config['agentId']}/contexts/{purpose}":
            payload={**payload,"runtimeProtocol":"lax-purpose-runtime/v3"}
        token=self.config["tokens"][purpose]
        headers={"Authorization":"Bearer "+token}
        if native_source:
            headers["X-Hollywood-Native-Source"]=json.dumps(native_source,separators=(",",":"))
        async with self.session.request(method,self.config["hollywoodUrl"]+"/hollywood/v3/"+path,
          headers=headers,json=payload) as r:
            value=await r.json()
            if r.status!=200:
                from .errors import HttpFailure
                raise HttpFailure(r.status,value.get("error","request failed"))
            return value

    async def serve(self, *, reconcile_only=False):
        loop=asyncio.get_running_loop()
        for sig in (signal.SIGTERM,signal.SIGINT):
            loop.add_signal_handler(sig,self.stop.set)
        async with ClientSession(timeout=ClientTimeout(total=15)) as self.session:
            try:
                for runner in self.runners.values():
                    await runner.start()
                if reconcile_only:
                    saved(self.reconcile_path,{"at":time.time(),"modelTurnsStarted":0,
                        "contexts":{p:{"nativeThread":r.thread,"held":r.failed} for p,r in self.runners.items()}})
                    return
                while not self.stop.is_set():
                    status={}
                    for purpose,runner in self.runners.items():
                        try:
                            pending=(await runner.request("pending"))["pending"]
                        except Exception as error:
                            status[purpose]={"active":runner.active,"held":runner.failed,
                                             "connection":"unavailable","error":type(error).__name__}
                            continue
                        cancelled=[x for x in pending if x["cancelled"]]
                        if purpose=="writer" and cancelled and runner.active:
                            await runner.cancel()
                        pending=[x for x in pending if not x["cancelled"]]
                        if purpose=="writer":
                            pending=pending[:1]  # A turn has one original effect/work owner.
                            key=[(x["id"],x.get("resume_revision",0)) for x in pending]
                        else:
                            key=[(x["id"],x["revision"]) for x in pending]
                        recovery=self.state/purpose/"recovery.json"
                        if recovery.exists():
                            control=json.loads(recovery.read_text())
                            key=[key,control["id"]]
                        fingerprint=hashlib.sha256(json.dumps(key).encode()).hexdigest()
                        last=self.state/purpose/"wake.json"
                        old=json.loads(last.read_text()) if last.exists() else {}
                        if not runner.active and not runner.failed and pending and old.get("fingerprint")!=fingerprint:
                            if old.get("state") in ("submission_intent","running","unknown"):
                                runner.failed=True
                            else:
                                runner.task=asyncio.create_task(runner.run(fingerprint,pending))
                                # Mark active before another scheduler pass can admit it.
                                runner.active=True
                        if runner.task and runner.task.done():
                            error=runner.task.exception()
                            if error:
                                runner.failed=True
                        status[purpose]={"active":runner.active,"held":runner.failed,
                                         "pending":pending,"nativeThread":runner.thread,
                                         "nativeTurn":runner.turn}
                    saved(self.status_path,{"at":time.time(),"agentId":self.config["agentId"],
                                                  "contexts":status,"modelsStartedByUnchangedPoll":0})
                    try:
                        await asyncio.wait_for(self.stop.wait(),0.5)
                    except TimeoutError:
                        pass
            finally:
                for runner in self.runners.values():
                    if runner.active:
                        try:
                            await runner.cancel()
                        except Exception:
                            pass
                for runner in self.runners.values():
                    if runner.task and not runner.task.done():
                        runner.task.cancel()
                await asyncio.gather(*(r.task for r in self.runners.values() if r.task),return_exceptions=True)
                for runner in self.runners.values():
                    if runner.activity:
                        try:
                            await runner.activity.flush(timeout=10)
                        except Exception as error:
                            runner.trace("activity_recovery_pending",{"error":type(error).__name__,
                                "pending":len(runner.activity.pending),"executionReplayed":False})
                        await runner.activity.close()
                await asyncio.gather(*(r.rpc.close() for r in self.runners.values()),return_exceptions=True)
                self.release_locks()

def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser()
    parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--reconcile-only",action="store_true")
    parser.add_argument("--purpose",choices=sorted(ROLES))
    args=parser.parse_args()
    asyncio.run(ContextAgent(json.loads(args.config.read_text()),purpose=args.purpose).serve(reconcile_only=args.reconcile_only))

if __name__=="__main__":
    main()
