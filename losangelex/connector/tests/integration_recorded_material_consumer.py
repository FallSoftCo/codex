"""Replay an actual captured native caller; local Responses fixture, not semantic proof."""
import asyncio,hashlib,json,os,re,time
from pathlib import Path
from aiohttp import web
from lax_connector.rpc import AppServer
from lax_connector.material_transport import tool_response
from lax_connector.journal import saved

def wire(v):return json.dumps(v,sort_keys=True,separators=(",",":"))
def fnv(s):
    value=2166136261
    for c in s:value=((value^ord(c))*16777619)&0xffffffff
    return value
def snap(reference,value):
    body=wire(value)
    return {"schema":"lax-context-material-snapshot/v1","reference":reference,"revision":3,
        "sha256":hashlib.sha256(body.encode()).hexdigest(),"totalBytes":len(body),
        "chunks":[{"offset":i,"content":body[i:i+3072]} for i in range(0,len(body),3072)]}
def output_text(item):
    out=item["output"]
    return "\n".join(x.get("text","") for x in out) if isinstance(out,list) else out

async def main():
    os.umask(0o077)
    root=Path(os.environ["RECORDED_MATERIAL_EVIDENCE"]);assert not root.exists();root.mkdir(mode=0o700)
    script_path=Path(os.environ["RECORDED_SCRIPT"]);source=script_path.read_text()
    digest=hashlib.sha256(source.encode()).hexdigest()
    assert digest==os.environ["RECORDED_SCRIPT_SHA256"],"Captured caller changed; never repair it to pass"
    refs=set(re.findall(r'reference:"([0-9a-f-]{36})"',source));assert len(refs)==1
    ref=next(iter(refs));expected=os.environ["EXPECT_PROGRAMMATIC_COMPATIBILITY"]=="1"
    value={"id":ref,"kind":"work","value":{"objective":"Disclosed recorded-caller fixture",
        "body":'a\\b"c\n'*6000,"marker":"end-of-exact-recorded-material"}}
    material=snap(ref,value);role=snap("role",{"role":"Disclosed mechanical fixture"})
    assert 38000<material["totalBytes"]<=98304
    observer='''const w=load("currentWork"); if(w===undefined) {text(JSON.stringify({observer:"recorded-read-v1",present:false}));} else {const s=JSON.stringify(w);let h=2166136261;for(let i=0;i<s.length;i++)h=Math.imul(h^s.charCodeAt(i),16777619)>>>0;text(JSON.stringify({observer:"recorded-read-v1",present:true,checksum:h,length:s.length}));}'''
    requests=[];events=[];calls=[];guarded=False;terminal=asyncio.Queue()
    async def provider(req):
        body=await req.json();requests.append(body);n=len(requests)
        assert n<=3,"No extra fixture inference"
        items=[{"type":"response.created","response":{"id":"recorded-"+str(n)}}]
        if n<=2:
            items.append({"type":"response.output_item.done","item":{"type":"custom_tool_call",
                "call_id":"recorded-original" if n==1 else "recorded-observer","name":"exec",
                "input":source if n==1 else observer}})
        items.append({"type":"response.completed","response":{"id":"recorded-"+str(n),
            "usage":{"input_tokens":0,"output_tokens":0,"total_tokens":0,"input_tokens_details":None,"output_tokens_details":None}}})
        return web.Response(text="".join("data: "+json.dumps(x)+"\n\n" for x in items),
                            content_type="text/event-stream")
    async def event(method,p):
        events.append({"method":method,"params":p})
        if method=="turn/completed":await terminal.put(p["turn"])
    async def tool(method,p):
        nonlocal guarded
        assert method=="item/tool/call"
        name=p["tool"];args=p["arguments"]
        if isinstance(args,str):args=json.loads(args)
        calls.append({"tool":name,"arguments":args})
        if name=="context_read":
            return {"success":True,"contentItems":[{"type":"inputText","text":json.dumps({"role":"role","work":[ref]})}]}
        assert name=="context_material_read" and args["reference"] in (ref,"role")
        count=sum(x["tool"]==name and x["arguments"].get("reference")==args["reference"] for x in calls)
        if count>3:
            guarded=True
            return {"success":False,"contentItems":[{"type":"inputText","text":"Fixture bound reached: repeated identical material read. No material supplied."}]}
        return tool_response(role if args["reference"]=="role" else material,
            "recorded-caller:"+str(len(calls)))
    app=web.Application();app.router.add_post("/v1/responses",provider)
    server=web.AppRunner(app);await server.setup();await web.TCPSite(server,"127.0.0.1",18795).start()
    settings={"cwd":str(root),"model":"gpt-6.1-sol","sandbox":"danger-full-access","approvalPolicy":"never",
        "baseInstructions":"Disclosed captured-caller mechanical fixture, no semantic model.",
        "dynamicTools":[{"name":name,"description":"Disclosed material fixture.",
            "inputSchema":{"type":"object","properties":{"reference":{"type":"string"},"revision":{"type":"integer"},"offset":{"type":"integer"}}}}
            for name in ["context_read","context_material_read"]],
        "toolPolicy":{"allowedTools":[{"name":name} for name in ["context_read","context_material_read","exec","wait"]]},
        "config":{"features.code_mode":True,"model_provider":"recorded_material_fixture",
            "model_providers.recorded_material_fixture":{"name":"Local recorded caller fixture","base_url":"http://127.0.0.1:18795/v1","wire_api":"responses","requires_openai_auth":False,"request_max_retries":0}}}
    binary=os.environ["MATERIAL_BINARY"]
    rpc=AppServer(binary,root/"home",root/"native",event,tool,enterprise=True)
    saved(root/"protocol.json",{"frozenAt":time.time(),"capturedScriptSha256":digest,"expectedCompatibility":expected,
        "SDKModule":tool_response.__module__,"binary":binary,"cases":"Exact unchanged original script, checksum-only observer; max3same-reference read attempts before disclosed fixture guard. Never repair result or caller. Native event/model output must not expose codeModeText field automatically.",
        "snapshotSha256":material["sha256"],"sourceBytes":material["totalBytes"],"localResponsesFixture":True,"providerModelRequests":0})
    try:
        await rpc.start()
        if expected:assert {"dynamic_tool_context_fragments/v1","dynamic_tool_code_mode_text/v1"}<=rpc.lax_capabilities
        x=await rpc.call("thread/start",settings);thread=x["thread"]["id"]
        x=await rpc.call("turn/start",{"threadId":thread,"input":[{"type":"text","text":"Disclosed recorded caller replay.","text_elements":[]}]})
        done=await asyncio.wait_for(terminal.get(),120)
        assert done["id"]==x["turn"]["id"] and len(requests)==3
        raw=[x for x in requests[-1]["input"] if x["type"]=="custom_tool_call_output" and x.get("call_id")=="recorded-observer"]
        assert len(raw)==1
        results=[json.loads(line) for line in output_text(raw[0]).splitlines() if line.startswith('{"observer":"recorded-read-v1"')]
        assert len(results)==1
        observed=results[0]
        expected_wire=wire(value)
        compatible=observed.get("present") is True and observed.get("checksum")==fnv(expected_wire) and observed.get("length")==len(expected_wire)
        assert compatible==expected,{"expected":expected,"observed":observed}
        if expected:
            assert not guarded
            assert sum(c["tool"]=="context_material_read" and c["arguments"]["reference"]==ref for c in calls)==1
            delivered=[]
            for item in requests[1]["input"]:
                if item["type"]!="function_call_output" or item.get("call_id") or item.get("name")!="context_material_read":continue
                fragment=json.loads(item["output"])
                if fragment.get("reference")==ref:delivered.append(fragment)
            content="".join(x["content"] for x in delivered)
            assert hashlib.sha256(content.encode()).hexdigest()==material["sha256"] and content==expected_wire
            # Callback activity carries the bounded receipt, not hidden computational data.
            dynamic=[e["params"]["item"] for e in events if e["method"]=="item/completed" and e["params"].get("item",{}).get("type")=="dynamicToolCall"]
            assert dynamic and all("codeModeText" not in d for d in dynamic)
            assert all(len(json.dumps(d.get("contentItems",[])).encode())<8192 for d in dynamic)
        saved(root/"result.json",{"at":time.time(),"state":"passed" if expected else "negative_control_rejected",
            "actualCompatibility":compatible,"observed":observed,"expectedChecksum":fnv(expected_wire),
            "nativeThread":thread,"materialCalls":len(calls),"loopGuardUsed":guarded,"capturedScriptUnchanged":digest,
            "providerModelRequests":0,"businessEffects":0,"scope":"Actual native+installed SDK, captured code-mode caller and exact stored-data checksum. Disclosed Responses fixture; no semantic architecture proof."})
        print(json.dumps({"state":"passed" if expected else "negative_control_rejected","actualCompatibility":compatible,"materialCalls":len(calls),"loopGuardUsed":guarded}),flush=True)
    except BaseException as error:
        saved(root/"failure.json",{"at":time.time(),"error":repr(error),"capturedScriptSha256":digest});raise
    finally:
        await rpc.close();await server.cleanup();saved(root/"requests.json",requests);saved(root/"events.json",events);saved(root/"calls.json",calls)
if __name__=="__main__":asyncio.run(main())
