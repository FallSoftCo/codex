"""SDK-only release authority for enrolled native nodes, without legacy workers.

This does not create a legacy controller, alter placement, settle old deliveries
or grant execution. Original native image/context and all semantic configuration
must remain unchanged; existing physical, service and local-I/O guards still run.
"""
import base64
from pathlib import Path
from . import native_image_upgrade as image,service_observer as observer
from .service_restart import file_hash
from .host import request


def sdk_only(plan):
    if (plan.get('retainedNative') is None or plan.get('sharedNativeUpgrade')
            or plan['oldBinary']!=plan['newBinary']):
        raise ValueError('Native-node authority only permits unchanged native SDK clients')
    target=plan['targets'][0]
    before=image.json.loads(base64.b64decode(target['before']))
    after=image.json.loads(base64.b64decode(target['after']))
    if (observer.digest(before)!=observer.digest(after) or before.get('runtimeMode')!='room-conversation'
            or not isinstance(before.get('nativeServer'),dict)
            or plan.get('transportAdoption',{}).get('historicalUnknown')is not None):
        raise ValueError('Native-node SDK release preserves exact semantic configuration and original context')
    return before


def validate(fd,config):
    node=image._json(fd,'native-node.json')
    if (node.get('schema')!='lax-native-node-enrollment/v1'
            or (node.get('authorityId'),node.get('hostId'),node.get('machineIdentity'))
            !=(config['authorityId'],config['hostId'],image.machine_identity())
            or node.get('nativeManifest')!=config['nativeServer']['manifest']):
        raise ValueError('Protected native-node enrollment differs from original host/transport')
    checksum,_=file_hash(Path(node['nativeManifest']),0)
    if checksum!=node.get('nativeManifestSha256'):
        raise ValueError('Originally enrolled native manifest changed')
    return node


def prepare(root,config,plan):
    fd=image._open_directory(root.parent.parent)
    try:
        try:image._json(fd,'controller.json')
        except FileNotFoundError:
            sdk_only(plan);node=validate(fd,config)
            return {'version':1,'registrationDigest':observer.digest(node),
                    'nativeManifestSha256':node['nativeManifestSha256']}
        return None
    finally:image.os.close(fd)


def load(fd,config,plan):
    if not plan.get('nativeNodeRegistration'):
        return image._json(fd,'controller.json')
    sdk_only(plan)
    try:image._json(fd,'controller.json')
    except FileNotFoundError:pass
    else:raise ValueError('Reviewed native-only host acquired a legacy controller')
    node=validate(fd,config)
    expected={'version':1,'registrationDigest':observer.digest(node),
              'nativeManifestSha256':node['nativeManifestSha256']}
    if plan['nativeNodeRegistration']!=expected:
        raise ValueError('Reviewed native-node registration changed')
    return node


def canonical(config,node,host,agent):
    """Authenticate the enrolled messaging principal, without execution claims."""
    value=request(config['hollywoodUrl'],config['token'],'GET','principals/'+agent)
    if (value.get('id')!=agent or value.get('authority')!=config['authorityId']
            or value.get('kind')!='agent' or value.get('active')is not True
            or value.get('home_node')!=host):
        raise ValueError('Original native messaging identity/home node is unavailable or changed')
