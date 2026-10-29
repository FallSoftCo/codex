"""Canonical bootstrap admission runs at the owner, never with copied host keys."""
from pathlib import Path
from uuid import UUID, uuid5
from .collaboration_bridge import digest, require
from .collaboration_capture import administrative_put


def register_resources(manifest, automatic, seeds, state, administrative, policy):
    from .collaboration_install import SUPPORTED_FEATURES
    host = manifest["hostId"]

    resource_policy = administrative("GET", "hosts/" + host + "/collaboration-bridge")
    from .resource_routing import capabilities
    capabilities(resource_policy)
    existing = resource_policy.get("bridge")
    if existing:
        require(
            existing["state"] == "active"
            and existing.get("features", []) == list(SUPPORTED_FEATURES)
            and existing["protocol"] == "canonical-edit-plans/v2"
            and str(existing["controller"]) == str(policy["controller"])
            and existing["adapter_sha256"] == manifest["adapterSha256"]
            and existing["enrollment_sha256"] == manifest["enrollmentSha256"],
            "Existing bridge differs or was revoked; explicit drained upgrade required",
        )
    else:
        payload = {
            "operationId": "install-bridge:" + manifest["enrollmentSha256"],
            "revision": 0,
            "controllerId": str(policy["controller"]),
            "state": "active",
            "protocol": "canonical-edit-plans/v2",
            "features": list(SUPPORTED_FEATURES),
            "adapterSha256": manifest["adapterSha256"],
            "enrollmentSha256": manifest["enrollmentSha256"],
        }
        administrative_put(
            state, administrative, "hosts/" + host + "/collaboration-bridge", payload
        )
    resources = []
    for root in automatic["resources"]:
        environment = digest({"hostId": host, "environmentId": root["environmentId"]})
        payload = {
            "operationId": "install-root:" + digest(root),
            "revision": 0,
            "state": "active",
            "rootPath": root["root"],
            "environmentSha256": environment,
            "rootIdentitySha256": digest(
                {
                    "hostId": host,
                    "environmentSha256": environment,
                    "device": root["device"],
                    "inode": root["inode"],
                }
            ),
            "registrationSha256": digest(root),
        }
        result = administrative_put(
            state,
            administrative,
            "hosts/" + host + "/physical-workspaces/" + root["workspaceId"],
            payload,
        )
        resources.append({**root, "registryRevision": result["workspace"]["revision"]})
    by_workspace = {root["workspaceId"]: root for root in resources}
    for agent, policy in seeds.items():
        for workspace in policy["workspaceIds"]:
            root = by_workspace[workspace]
            payload = {"operationId": "install-agent-access:" + digest([agent, workspace, root["registryRevision"]]),
                       "revision": 0, "workspaceRevision": root["registryRevision"],
                       "executionHost": host, "state": "active", "canRead": True, "canWrite": True}
            administrative_put(state, administrative,
                "physical-workspaces/" + workspace + "/agent-grants/" + str(UUID(agent)), payload)
    from .resource_routing import seed_defaults
    routing_defaults = seed_defaults(state, administrative, manifest["authorityId"], host, seeds, by_workspace)
    return resources, routing_defaults


def validate_proposal(value):
    require(set(value) == {'schema','authorityId','hostId','machineIdentity','hollywoodUrl',
                           'adapterSha256','enrollmentSha256','resources','agents'},
            'Exact public proposal fields required; credentials are never accepted')
    require(value['schema']=='lax-collaboration-admission-proposal/v1', 'Explicit proposal schema required')
    UUID(value['authorityId']); host=str(UUID(value['hostId']))
    for key in ('machineIdentity','adapterSha256','enrollmentSha256'):
        require(isinstance(value[key],str) and len(value[key])==64
                and all(c in '0123456789abcdef' for c in value[key]), 'Canonical proposal digest required')
    require(isinstance(value['resources'],list) and 1<=len(value['resources'])<=8
            and isinstance(value['agents'],dict) and 1<=len(value['agents'])<=32,
            'Bounded explicit resource and agent proposal required')
    roots=[]; identities=set()
    for root in value['resources']:
        require(set(root)=={'hostId','environmentId','root','device','inode','workspaceId'}
                and root['hostId']==host and root['environmentId']=='local'
                and type(root['device']) is int and root['device']>=0
                and type(root['inode']) is int and root['inode']>0,
                'Exact host-local root identity required')
        path=Path(root['root'])
        require(path.is_absolute() and str(path)!='/' and '..' not in path.parts
                and str(path)==root['root'] and all(not path.is_relative_to(old)
                and not old.is_relative_to(path) for old in roots), 'Distinct nonnested literal roots required')
        environment=digest({'hostId':host,'environmentId':'local'})
        expected=str(uuid5(UUID(host),'physical-root:'+digest([environment,root['device'],root['inode']])))
        require(root['workspaceId']==expected and expected not in identities,
                'Workspace identity must derive from the reviewed physical root')
        identities.add(expected); roots.append(path)
    for agent,seed in value['agents'].items():
        UUID(agent)
        require(set(seed)=={'workspaceIds','defaultWorkspaceId'}
                and isinstance(seed['workspaceIds'],list) and seed['workspaceIds']
                and len(set(seed['workspaceIds']))==len(seed['workspaceIds'])
                and set(seed['workspaceIds'])<=identities
                and seed['defaultWorkspaceId'] in seed['workspaceIds'],
                'Agent access/default must name reviewed roots only')
    return value


def _proposal(directory, manifest):
    from .service_observer import protected
    proposal = validate_proposal(protected(Path(directory) / 'admission.prepared.json'))
    require(proposal.get('schema') == 'lax-collaboration-admission-proposal/v1'
            and digest(proposal) == manifest['admissionProposalSha256'],
            'Original public admission proposal changed')
    require((proposal['authorityId'], proposal['hostId'], proposal['adapterSha256'],
             proposal['enrollmentSha256']) ==
            (manifest['authorityId'], manifest['hostId'], manifest['adapterSha256'],
             manifest['enrollmentSha256']), 'Admission proposal scope differs')
    return proposal


def admit(proposal_path, administrator_path, destination):
    """Owner-side canonical admission; consumes no remote host credential."""
    import os
    from .collaboration_install import protected_tree, write_original
    from .service_observer import protected
    from .host import request
    require(os.geteuid() == 0, 'Protected owning administrator required')
    proposal = validate_proposal(protected(Path(proposal_path)))
    require(proposal.get('schema') == 'lax-collaboration-admission-proposal/v1',
            'Explicit public admission proposal required')
    admin = protected(Path(administrator_path))
    require(admin['authorityId'] == proposal['authorityId'], 'Admission authority differs')
    # This URL is independently configured by the administrator, not a proposal-
    # supplied endpoint. Never send the owner credential to a remote proposal URL.
    http = lambda method, route, payload=None: request(admin['hollywoodUrl'], admin['token'], method, route, payload)
    state = protected_tree(destination, 0o700)
    protected_tree(state / "administration", 0o700)
    manifest = {k: proposal[k] for k in ('authorityId','hostId','adapterSha256','enrollmentSha256')}
    from .capture_protocol import HOST_SCOPED_CAPTURE
    automatic = {'schema': HOST_SCOPED_CAPTURE, 'resources': proposal['resources']}
    require(digest(automatic) == proposal['enrollmentSha256'], 'Resource enrollment digest differs')
    policy = http('GET', 'hosts/'+proposal['hostId']+'/admission')['policy']
    require(policy and policy['machine_identity'] == proposal['machineIdentity'],
            'Canonical host machine differs from proposal')
    resources, defaults = register_resources(manifest, automatic, proposal['agents'], state, http, policy)
    receipt = {'schema':'lax-collaboration-admission-receipt/v1',
               'proposalSha256':digest(proposal), 'authorityId':proposal['authorityId'],
               'hostId':proposal['hostId'], 'controllerId':str(policy['controller']),
               'resources':resources,'resourceDefaults':defaults,
               'modelsStarted':0,'servicesStarted':0}
    write_original(state/'admission.accepted.json', receipt)
    return receipt


def accepted_resources(directory, manifest, bridge, seeds, relay, policy):
    """Local publication verifies the owner receipt and live canonical bridge.

    The runtime still reauthorizes grants for each native operation. The receipt
    never substitutes for execution/lock/permit admission.
    """
    from .service_observer import protected
    proposal = _proposal(directory, manifest)
    receipt = protected(Path(directory)/'admission.accepted.json')
    require(receipt.get('schema') == 'lax-collaboration-admission-receipt/v1'
            and receipt.get('proposalSha256') == digest(proposal)
            and (receipt.get('authorityId'), receipt.get('hostId'), receipt.get('controllerId'))
            == (manifest['authorityId'], manifest['hostId'], str(policy['controller'])),
            'Owning admission receipt scope differs')
    require(digest(seeds) == digest(proposal['agents']), 'Agent resource policy changed')
    current = relay('GET','hosts/'+manifest['hostId']+'/collaboration-bridge').get('bridge')
    require(current and current['state']=='active'
            and current['protocol']=='canonical-edit-plans/v2'
            and current.get('features',[])==['canonical-work-resource-routing/v1']
            and str(current['controller'])==str(policy['controller'])
            and current['adapter_sha256']==manifest['adapterSha256']
            and current['enrollment_sha256']==manifest['enrollmentSha256'],
            'Canonical bridge admission changed or was revoked')
    resources=receipt['resources']
    require(len(resources)==len(proposal['resources']) and all(
        {k:v for k,v in row.items() if k!='registryRevision'}==original
        and type(row.get('registryRevision')) is int and row['registryRevision']>0
        for row,original in zip(resources,proposal['resources'])),
        'Accepted resources differ from reviewed local roots')
    return resources, receipt['resourceDefaults']


def main():
    import argparse,json,os
    os.umask(0o077)
    parser=argparse.ArgumentParser()
    parser.add_argument('--proposal',type=Path,required=True)
    parser.add_argument('--administrator',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args()
    value=admit(args.proposal,args.administrator,args.destination)
    print(json.dumps({'accepted':True,'authorityId':value['authorityId'],
                      'hostId':value['hostId'],'modelsStarted':0,'servicesStarted':0}))


if __name__=='__main__':
    main()
