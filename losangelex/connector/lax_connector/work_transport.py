"""Captured work routing, independent of an agent's home and idle transport.

A node is selected only from the original canonical claim, never model text or
previous global selection. Context-local scope follows native child tasks and
is restored after completion/failure. Named-resource server routing still takes
precedence when a tool explicitly reads another room or delivery.
"""
import contextlib
import contextvars
import functools
import json
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class WorkRoute:
    authority: str
    node: str
    delivery: str
    generation: int


current = contextvars.ContextVar('lax_captured_work_route',default=None)


def captured(claim,config):
    d=claim['delivery'];request=claim['request']
    nodes={str(UUID(str(n))) for n in (claim.get('ownerNodeId'),d.get('ownerNodeId')) if n is not None}
    if not nodes:return None  # Retained pre-federation claims keep their old transport.
    if len(nodes)!=1 or str(d['agent'])!=config['agentId'] or d['authority']!=request['authority']:
        raise ValueError('Work route differs from original claimed participant')
    authority=str(UUID(str(request['authority'])))
    expected=config.get('federationAuthorityId',config.get('authorityId'))
    if expected is not None and str(UUID(expected))!=authority:
        raise ValueError('Claimed organization differs from installed agent')
    if type(d['generation']) is not int or d['generation']<1:
        raise ValueError('Original work generation required')
    return WorkRoute(authority,next(iter(nodes)),str(UUID(str(d['id']))),d['generation'])


@contextlib.contextmanager
def scope(claim,config):
    token=current.set(captured(claim,config))
    try:yield
    finally:current.reset(token)


def claimed(function):
    @functools.wraps(function)
    async def wrapped(self,*args,**kwargs):
        with scope(self.active,self.config):
            return await function(self,*args,**kwargs)
    return wrapped


def journaled(function):
    @functools.wraps(function)
    async def wrapped(self,*args,**kwargs):
        original=json.loads(self.journal.read_text())
        with scope(original,self.config):
            return await function(self,*args,**kwargs)
    return wrapped
