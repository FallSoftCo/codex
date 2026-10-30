"""Independent deterministic observation lanes; never starts an agent or model."""
import contextvars
import fcntl
import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID

from .journal import saved

current_node = contextvars.ContextVar('host_observation_node', default=None)


def receipt(config, name):
    node = config.get('_observationNode')
    prefix = 'node-' + str(UUID(node)) + '-' if node else ''
    return Path(config['state']) / (prefix + name)


def serve(config, *, once=False):
    nodes=config['observationNodes']
    if (not isinstance(nodes,list) or not 1<=len(nodes)<=8
            or len({str(UUID(n)) for n in nodes})!=len(nodes)):
        raise ValueError('One to eight distinct reviewed observation node IDs required')
    nodes=[str(UUID(n)) for n in nodes]
    root=Path(config['state']);root.mkdir(mode=0o700,parents=True,exist_ok=True)
    lease=(root/'controller.lock').open('a')
    fcntl.flock(lease.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    states={node:{'state':'starting'} for node in nodes};guard=threading.Lock()

    def publish(node,value):
        with guard:
            states[node]={**value,'observedAt':time.time()}
            report={
                'schema':'lax-host-observation-sources/v1','localNodeId':nodes[0],
                'state':'healthy' if all(v['state']=='healthy' for v in states.values()) else 'degraded',
                'sources':dict(states),'modelsStarted':0}
            saved(root/'observation-sources.json',report)
            saved(root/'status.json',{
                **states[nodes[0]],
                'state':states[nodes[0]]['state'],
                'federation':report,
                'meaning':'Local host health and each remote observation lane are distinct',
                'modelsStarted':0})

    def lane(node):
        from .host import supervise
        cfg={k:v for k,v in config.items() if k!='observationNodes'}
        cfg.update(_observationNode=node,_observeServices=node==nodes[0])
        token=current_node.set(node);failures=0
        try:
            while True:
                try:
                    value=supervise(cfg,once=True)
                    status=json.loads(receipt(cfg,'status.json').read_text())
                    publish(node,status);failures=0
                    if once:return {'nodeId':node,'receipt':value,'state':status['state']}
                    delay=config.get('sampleSeconds',5)
                except Exception as error:
                    failures+=1
                    publish(node,{'state':'held','error':type(error).__name__,'modelsStarted':0})
                    if once:return {'nodeId':node,'state':'held','error':type(error).__name__}
                    delay=min(60,config.get('sampleSeconds',5)*2**min(failures-1,4))*random.uniform(.9,1.1)
                time.sleep(delay)
        finally:current_node.reset(token)

    # One bounded lane per explicitly enrolled node. A dead peer never delays
    # fresh local capacity/registration. This is ordinary I/O, not model polling.
    try:
        with ThreadPoolExecutor(max_workers=len(nodes),thread_name_prefix='host-observer') as pool:
            results=list(pool.map(lane,nodes))
        return {'schema':'lax-host-observation-sources/v1','sources':results,'modelsStarted':0}
    finally:lease.close()
