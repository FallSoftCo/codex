"""Real HTTP, interleaved synthetic work scopes; no native process or model."""
import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4
from aiohttp import web,ClientSession
from lax_connector.connector import Connector
from lax_connector import work_transport


async def main(out):
    out.mkdir(mode=0o700,parents=True,exist_ok=False)
    seen=[]
    async def observe(request):
        value={'node':request.headers.get('X-Hollywood-Work-Node'),
               'authority':request.headers.get('X-Hollywood-Authority'),
               'agent':request.headers.get('X-Hollywood-Agent')}
        seen.append(value);await asyncio.sleep(.01)
        return web.json_response(value)
    app=web.Application();app.router.add_get('/hollywood/v3/{path:.*}',observe)
    runner=web.AppRunner(app);await runner.setup()
    site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
    authority,agent,host,node_a,node_b=[str(uuid4()) for _ in range(5)]
    config={'runtimeMode':'single-context','state':str(out/'state'),'agentId':agent,'hostId':host,
            'token':'SYNTHETIC-LOCAL-ONLY','federationAuthorityId':authority,
            'hollywoodUrl':'http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])}
    connector=Connector(config)
    def claim(node):
        return {'ownerNodeId':node,'delivery':{'ownerNodeId':node,'id':str(uuid4()),
            'agent':agent,'authority':authority,'generation':1},'request':{'authority':authority}}
    class Probe:
        def __init__(self,value):self.active=value;self.config=config
        @work_transport.claimed
        async def read(self):
            await asyncio.sleep(.01)
            a=await connector._http('GET','hosts/'+host+'/admission')
            await asyncio.sleep(.01)
            b=await connector._http('GET','connector/deliveries/'+self.active['delivery']['id']+'/context')
            return a,b
        @work_transport.claimed
        async def fail(self):
            await connector._http('GET','hosts/'+host+'/admission')
            raise RuntimeError('SYNTHETIC preparation failure')
        @work_transport.journaled
        async def reconcile(self):return await connector._http('GET','hosts/'+host+'/admission')
    try:
        async with ClientSession() as connector.session:
            first,second=Probe(claim(node_a)),Probe(claim(node_b))
            a,b=await asyncio.gather(first.read(),second.read())
            assert all(v['node']==node_a and v['authority']==authority and v['agent']==agent for v in a)
            assert all(v['node']==node_b and v['authority']==authority and v['agent']==agent for v in b)
            idle=await connector._http('GET','agents/'+agent+'/role');assert idle['node'] is None
            try:await first.fail()
            except RuntimeError as error:assert str(error)=='SYNTHETIC preparation failure'
            else:raise AssertionError('Expected synthetic error')
            assert (await connector._http('GET','agents/'+agent+'/role'))['node'] is None
            second.journal=out/'original-claim.json';second.journal.write_text(json.dumps(second.active))
            assert (await second.reconcile())['node']==node_b
            legacy=claim(node_a);legacy.pop('ownerNodeId');legacy['delivery'].pop('ownerNodeId')
            assert all(v['node'] is None for v in await Probe(legacy).read())
            bad=claim(node_a);bad['ownerNodeId']=node_b;before=len(seen)
            try:await Probe(bad).read()
            except ValueError:pass
            else:raise AssertionError('Conflicting canonical owner accepted')
            assert len(seen)==before and work_transport.current.get() is None and connector.rpc is None
        result={'passed':True,'actualHttpRequests':len(seen),'concurrentWorkScopesIsolated':True,
                'idleHomeReadUnscoped':True,'failureRestoresScope':True,'originalJournalRestoresOwner':True,
                'conflictingOwnerRejectedBeforeTransport':True,'legacyClaimsUnchanged':True,
                'nativeProcessesStarted':0,'modelsStarted':0,'claimsAreSynthetic':True}
        (out/'qualification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    finally:
        connector.lock.close();await runner.cleanup()


if __name__=='__main__':asyncio.run(main(Path(sys.argv[1])))
