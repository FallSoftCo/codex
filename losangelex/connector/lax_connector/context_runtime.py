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
        self.declarations=tools(purpose)
        self.allowed={t["name"] for t in self.declarations}
        self.rpc=AppServer(self.config["binary"],Path(self.config["homes"][purpose]),
          self.state/"native",self.event,self.tool,enterprise=True,isolated_process_group=True)

    def trace(self,event,value):
        with (self.state/"events.jsonl").open("a") as f:
            f.write(json.dumps({"at":time.time(),"event":event,**value},default=str)+"\n")

    async def request(self,action,value=None,operation=None,turn=None):
        operation=operation or str(uuid4())
        payload={"operationId":operation,"action":action,"nativeThread":self.thread,
                 "nativeTurn":turn or self.turn or "runtime","value":value or {}}
        path=f"agents/{self.config['agentId']}/contexts/{self.purpose}"
        if action=="pending":
            return await self.agent.http(self.purpose,"POST",path,payload)
        journal=self.state/("operation-"+hashlib.sha256(operation.encode()).hexdigest()+".json")
        if journal.exists():
            old=json.loads(journal.read_text())
            if old["request"]!=payload:
                raise RuntimeError("Original context operation changed")
            if old.get("receipt") is not None:
                return old["receipt"]
            # An uncertain original is observed, never submitted a second time.
            result=await self.agent.http(self.purpose,"GET",path+"/operations/"+operation)
        else:
            saved(journal,{"request":payload,"state":"intent"})
            try:
                result=await self.agent.http(self.purpose,"POST",path,payload)
            except Exception:
                result=await self.agent.http(self.purpose,"GET",path+"/operations/"+operation)
        saved(journal,{"request":payload,"state":"accepted","receipt":result})
        return result

    async def start(self):
        await self.rpc.start()
        await external_admission(self.rpc,False)
        # Code-mode models reach the filtered inner tools through exec/wait.
        # These wrappers confer no access to tools excluded by the native ceiling.
        allowed=[{"name":name} for name in sorted(self.allowed | {"exec","wait"})]
        if self.purpose=="writer":
            allowed += [{"name":name} for name in ("exec_command","write_stdin","apply_patch","update_plan")]
        settings={"cwd":self.config["workspace"],"model":self.config["model"],
          "sandbox":self.config.get("sandbox","danger-full-access"),
          "approvalPolicy":self.config.get("approvalPolicy","never"),
          "baseInstructions":COMMON+ROLES[self.purpose],
          "developerInstructions":"",
          "dynamicTools":self.declarations,"toolPolicy":{"allowedTools":allowed},
          "config":{"features.goal_external_admission":True,
            "features.goal_external_lifecycle":False,"agents.enabled":False,
            "features.multi_agent":False,"features.multi_agent_v2":False,
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
        await self.request("bind",operation="bind:"+self.config["contextIds"][self.purpose]+":"+self.thread,turn="bootstrap")
        self.trace("context_started",{"threadId":self.thread,"tools":sorted(self.allowed),
                                    "effectiveToolPolicy":result.get("toolPolicy")})
        # Resume changes metadata only. An unresolved original is observed,
        # never converted into another model submission.
        wake=self.state/"wake.json"
        old=json.loads(wake.read_text()) if wake.exists() else {}
        if old.get("state") in ("submission_intent","running","unknown"):
            self.turn=old.get("nativeTurn")
            if not self.turn:
                self.failed=True
                self.trace("recovery_held",{"reason":"Original submission identity unavailable"})
            else:
                observed=await original_turn(self,self.turn)
                saved(self.state/"recovery-observation.json",{
                    "originalWake":old,"nativeTurn":self.turn,"turn":observed,"modelTurnsStarted":0})
                if observed["status"] in TERMINAL:
                    await self.request("end",{"status":observed["status"]},
                                       operation="context-end:"+self.turn)
                    saved(wake,{**old,"state":"finished","turn":observed,"recovered":True})
                else:
                    self.failed=True
                    self.trace("recovery_held",{"nativeTurn":self.turn,"status":observed["status"]})

    async def event(self,method,params):
        if params.get("threadId") not in (None,self.thread):
            return
        self.trace(method,params)
        if method=="turn/started" and self.active and self.turn is None:
            self.turn=params["turn"]["id"]
            old=json.loads((self.state/"wake.json").read_text())
            saved(self.state/"wake.json",{**old,"nativeTurn":self.turn})
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
                or method!="item/tool/call" or params.get("threadId")!=self.thread
                or params.get("turnId")!=self.turn):
                raise PermissionError("Original native turn no longer admits this callback")
            name=params["tool"]
            if name not in self.allowed:
                raise PermissionError("Tool belongs to another context purpose")
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

    async def run(self,fingerprint,pending):
        self.active=True
        self.turn=None
        self.accepting=False
        self.closing=False
        self.admitted.clear()
        self.finished=asyncio.get_running_loop().create_future()
        saved(self.state/"wake.json",{"fingerprint":fingerprint,"state":"submission_intent",
                                      "pending":pending,"nativeThread":self.thread})
        self.trace("wake",{"fingerprint":fingerprint,"pending":pending})
        try:
            result=await self.rpc.call("turn/start",{
              "threadId":self.thread,"input":[],"model":self.config["model"],
              "effort":self.config["effort"],"turnTrigger":"hollywood_context_material",
              "toolOutput":{"name":"context_material_available",
                "output":json.dumps({"purpose":self.purpose,"materialIds":[r["id"] for r in pending]}),
                "retain":False}})
            self.turn=result["turn"]["id"]
            await self.request("begin",{"materialIds":[r["id"] for r in pending]},
                               operation="context-begin:"+self.turn)
            self.accepting=True
            self.admitted.set()
            saved(self.state/"wake.json",{"fingerprint":fingerprint,"state":"running",
                                         "nativeThread":self.thread,"nativeTurn":self.turn})
            turn=await wait_terminal(self)
            self.accepting=False
            async with self.effect_lock:
                await self.request("end",{"status":turn["status"]},
                                   operation="context-end:"+self.turn)
            saved(self.state/("turn-"+self.turn+".json"),{"fingerprint":fingerprint,
                 "nativeThread":self.thread,"nativeTurn":self.turn,"turn":turn})
            saved(self.state/"wake.json",{"fingerprint":fingerprint,"state":"finished",
                                         "nativeThread":self.thread,"nativeTurn":self.turn,"turn":turn})
        except BaseException as error:
            self.accepting=False
            self.failed=True
            if self.turn and (not self.finished or not self.finished.done()):
                try:
                    await self.cancel()
                except Exception as cleanup:
                    self.trace("interrupt_unconfirmed",{"error":str(cleanup),"nativeTurn":self.turn})
                    self.agent.stop.set()
            saved(self.state/"wake.json",{"fingerprint":fingerprint,"state":"unknown",
                     "nativeThread":self.thread,"nativeTurn":self.turn,"error":str(error)})
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
    def __init__(self,config):
        self.config=config
        self.state=Path(config["state"])
        self.state.mkdir(mode=0o700,exist_ok=True)
        self.lock=(self.state/"agent.lock").open("a")
        fcntl.flock(self.lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.runners={p:ContextRunner(self,p) for p in ROLES}
        self.session=None
        self.stop=asyncio.Event()

    async def http(self,purpose,method,path,payload=None):
        token=self.config["tokens"][purpose]
        async with self.session.request(method,self.config["hollywoodUrl"]+"/hollywood/v3/"+path,
          headers={"Authorization":"Bearer "+token},json=payload) as r:
            value=await r.json()
            if r.status!=200:
                raise RuntimeError(f"Hollywood {r.status}: {value.get('error','request failed')}")
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
                    saved(self.state/"reconcile-only.json",{"at":time.time(),"modelTurnsStarted":0,
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
                    saved(self.state/"status.json",{"at":time.time(),"agentId":self.config["agentId"],
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
                await asyncio.gather(*(r.rpc.close() for r in self.runners.values()),return_exceptions=True)

def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser()
    parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--reconcile-only",action="store_true")
    args=parser.parse_args()
    asyncio.run(ContextAgent(json.loads(args.config.read_text())).serve(reconcile_only=args.reconcile_only))

if __name__=="__main__":
    main()
