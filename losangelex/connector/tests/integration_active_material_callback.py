"""Actual native ACTIVE callback transport. Local Responses fixture, no semantic claim."""
import asyncio,hashlib,json,os,sys,time
from pathlib import Path
if not os.environ.get("ACTIVE_MATERIAL_INSTALLED"):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from lax_connector.rpc import AppServer
from lax_connector.material_transport import tool_response,fragments
from lax_connector import material_transport as material_module
from lax_connector.native_context_rebuild import observe_history
from lax_connector.journal import saved

def snapshot():
    encoded=json.dumps({"source":"Disclosed transport fixture","body":'a\\b"c\n'*7000},
                       sort_keys=True,separators=(",",":"))
    return {"schema":"lax-context-material-snapshot/v1","reference":"role","revision":3,
        "sha256":hashlib.sha256(encoded.encode()).hexdigest(),"totalBytes":len(encoded),
        "chunks":[{"offset":i,"content":encoded[i:i+3072]} for i in range(0,len(encoded),3072)]}

async def journey(root,binary,kind):
    root.mkdir(mode=0o700)
    requests=[];events=[];finished=asyncio.Queue();called=asyncio.Event();release=asyncio.Event()
    material=snapshot();operation="active-callback-r280:"+kind
    expected=fragments(material,operation)
    async def provider(req):
        body=await req.json();requests.append(body);index=len(requests)
        values=[{"type":"response.created","response":{"id":"fixture-"+str(index)}}]
        if index==1 and kind=="complete-codemode":
            values.append({"type":"response.output_item.done","item":{"type":"custom_tool_call",
                "call_id":"material-exec","name":"exec",
                "input":'text(await tools.context_material_read({reference:"role"}));'}})
        elif index==1:
            values.append({"type":"response.output_item.done","item":{"type":"function_call",
                "call_id":"material-call","name":"context_material_read",
                "arguments":json.dumps({"reference":"role"})}})
        values.append({"type":"response.completed","response":{"id":"fixture-"+str(index),
            "usage":{"input_tokens":0,"output_tokens":0,"total_tokens":0,
                     "input_tokens_details":None,"output_tokens_details":None}}})
        return web.Response(text="".join("data: "+json.dumps(v)+"\n\n" for v in values),
                            content_type="text/event-stream")
    async def event(method,p):
        events.append({"method":method,"params":p})
        if method=="turn/completed":await finished.put(p["turn"])
    async def tool(method,p):
        assert method=="item/tool/call" and p["tool"]=="context_material_read"
        called.set()
        if kind=="cancelled":await release.wait()
        answer=tool_response(material,operation)
        if kind=="invalid":
            answer["contextFragments"]=[answer["contextFragments"][0],"x"*8193]
        return answer
    app=web.Application();app.router.add_post("/v1/responses",provider)
    server=web.AppRunner(app);await server.setup()
    await web.TCPSite(server,"127.0.0.1",18795).start()
    settings={"cwd":str(root),"model":"gpt-6.1-sol","sandbox":"danger-full-access",
        "approvalPolicy":"never","baseInstructions":"Disclosed transport mechanism fixture.",
        "dynamicTools":[{"name":"context_material_read","description":"Read material.",
            "inputSchema":{"type":"object","properties":{"reference":{"type":"string"}},
                           "required":["reference"],"additionalProperties":False}}],
        "toolPolicy":{"allowedTools":[{"name":name} for name in ["context_material_read","exec","wait"]]},
        "config":{"features.code_mode":True,"model_provider":"active_material_probe",
            "model_providers.active_material_probe":{"name":"Local transport fixture",
                "base_url":"http://127.0.0.1:18795/v1","wire_api":"responses",
                "requires_openai_auth":False,"request_max_retries":0}}}
    rpc=AppServer(binary,root/"home",root/"native",event,tool,enterprise=True)
    try:
        await rpc.start()
        assert "dynamic_tool_context_fragments/v1" in rpc.lax_capabilities
        x=await rpc.call("thread/start",settings);thread=x["thread"]["id"]
        started=await rpc.call("turn/start",{"threadId":thread,"input":[{"type":"text",
            "text":"Disclosed active callback mechanics, no semantic model inference.",
            "text_elements":[]}]})
        turn=started["turn"]["id"]
        await asyncio.wait_for(called.wait(),60)
        if kind=="cancelled":
            await rpc.call("turn/interrupt",{"threadId":thread,"turnId":turn})
        terminal=await asyncio.wait_for(finished.get(),90)
        assert terminal["id"]==turn
        if kind=="cancelled":
            assert terminal["status"]=="interrupted";release.set()
            # Exact late callback is allowed to settle; it cannot attach to a later turn.
            await asyncio.wait_for(asyncio.gather(*list(rpc.requests)),20)
            assert len(requests)==1
        else:
            assert terminal["status"]=="completed"
            assert len(requests)==2
            got=[item["output"] for item in requests[1]["input"]
                 if item["type"]=="function_call_output"
                 and item.get("name")=="context_material_read" and not item.get("call_id")]
            assert got==([item["output"] for item in expected] if kind.startswith("complete") else [])
        observed=await rpc.call("thread/read",{"threadId":thread,"includeTurns":False})
        path=observed["thread"]["path"]
        history=Path(path).read_text()
        if kind.startswith("complete"):
            assert observe_history(path,[{**i,"name":"context_material_read","namespace":None}
                for i in expected])["allFragmentsObserved"]
        else:
            assert "lax-context-material-fragment/v1" not in history
        await rpc.close()
        rpc=AppServer(binary,root/"home",root/"reopened-native",event,tool,enterprise=True)
        await rpc.start()
        resumed=await rpc.call("thread/resume",{**settings,"threadId":thread,"excludeTurns":True})
        assert resumed["thread"]["id"]==thread
        before=len(requests)
        x=await rpc.call("turn/start",{"threadId":thread,"input":[{"type":"text",
            "text":"Disclosed cold reopen mechanics.","text_elements":[]}]})
        terminal=await asyncio.wait_for(finished.get(),60)
        assert terminal["id"]==x["turn"]["id"] and terminal["status"]=="completed"
        assert len(requests)==before+1
        got=[i["output"] for i in requests[-1]["input"] if i["type"]=="function_call_output"
             and i.get("name")=="context_material_read" and not i.get("call_id")]
        assert got==([i["output"] for i in expected] if kind.startswith("complete") else [])
        result={"kind":kind,"sameNativeThread":thread,"responseFixtureRequests":len(requests),
            "fragmentsExpected":len(expected),"fragmentsObservedAfterReopen":len(got),
            "actualProviderModelRequests":0,"businessEffects":0}
        saved(root/"result.json",result);return result
    finally:
        release.set();await rpc.close();await server.cleanup()
        saved(root/"events.json",events);saved(root/"requests.json",requests)

async def main():
    os.umask(0o077)
    root=Path(os.environ["ACTIVE_MATERIAL_EVIDENCE"])
    assert not root.exists(),"Inspect original mechanism qualification; do not overwrite"
    root.mkdir(mode=0o700)
    saved(root/"protocol.json",{"schema":"lax-active-material-mechanics/v1",
        "frozenAt":time.time(),"sourceSha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "cases":["complete active direct and code-mode callback: next request full bounded fragments, cold reopen same thread",
                 "invalid batch: first valid fragment plus oversize fragment, zero appended",
                 "cancelled original callback: late response cannot append to new turn"],
        "localResponsesFixture":True,"semanticModelClaim":False,
        "loadedSDKModule":material_module.__file__})
    results=[]
    try:
        for kind in ["complete","complete-codemode","invalid","cancelled"]:
            results.append(await journey(root/kind,os.environ["MATERIAL_BINARY"],kind))
    except BaseException as error:
        saved(root/"failure.json",{"at":time.time(),"error":repr(error),"casesCompleted":results})
        raise
    saved(root/"result.json",{"at":time.time(),"state":"passed","cases":results,
        "scope":"Actual native active callback, persistence and cold reopen with disclosed local Responses fixture. Zero external model calls; not proof of semantic behavior."})
    print(json.dumps({"state":"passed","cases":results}),flush=True)

if __name__=="__main__":asyncio.run(main())
