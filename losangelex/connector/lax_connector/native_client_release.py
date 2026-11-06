"""SDK-only native-client releases use existing managed-service enrollment.

Execution controllers and optional historical node annotations are not client
release authority. The original service enrollment, unchanged native dependency,
complete software closure, quiet contexts and local I/O remain independently
verified by the existing release machinery. No placement or delivery is changed.
"""
import base64
from . import native_image_upgrade as image,service_observer as observer
from .host import request


def prepare(plan):
    if (plan.get('retainedNative') is None or plan.get('sharedNativeUpgrade')
            or plan['oldBinary']!=plan['newBinary']):return None
    target=plan['targets'][0]
    before=image.json.loads(base64.b64decode(target['before']))
    after=image.json.loads(base64.b64decode(target['after']))
    if (observer.digest(before)!=observer.digest(after) or before.get('runtimeMode')!='room-conversation'
            or not isinstance(before.get('nativeServer'),dict)
            or plan.get('transportAdoption',{}).get('historicalUnknown')is not None):return None
    enrolled=plan['priorEnrollment']
    if ([enrolled.get(k)for k in ('authorityId','hostId','agentId')]!=plan['scope']
            or enrolled.get('machineIdentity')!=image.machine_identity()
            or [before.get(k)for k in ('authorityId','hostId','agentId')]!=plan['scope']):
        raise ValueError('Original managed native-client enrollment differs from host or identity')
    return {'version':1,'kind':'native-client-sdk','enrollmentDigest':observer.digest(enrolled),
            'dependencyDigest':observer.digest(plan['retainedNative'])}


def load(fd,config,plan):
    if not plan.get('nativeClientBoundary'):
        return image._json(fd,'controller.json')
    expected=prepare(plan)
    before=image.json.loads(base64.b64decode(plan['targets'][0]['before']))
    if expected is None or plan['nativeClientBoundary']!=expected or observer.digest(config)!=observer.digest(before):
        raise ValueError('Reviewed unchanged native-client boundary changed')
    return {**expected,'authorityId':config['authorityId'],'hostId':config['hostId'],
            'agentId':config['agentId'],'machineIdentity':plan['priorEnrollment']['machineIdentity']}


def canonical(config,control,host,agent):
    """Authenticate the original messaging identity; never query legacy workers."""
    value=request(config['hollywoodUrl'],config['token'],'GET','principals/'+agent)
    if (value.get('id')!=agent or value.get('authority')!=config['authorityId']
            or value.get('kind')!='agent' or value.get('active')is not True
            or value.get('home_node')!=host):
        raise ValueError('Original native messaging identity/home node is unavailable or changed')
