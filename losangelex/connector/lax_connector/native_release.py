"""Reviewed immutable software closure; original provisioning remains historical."""

import base64
import hashlib
import json
import os
import pwd
import re
import subprocess
from pathlib import Path
from uuid import UUID

from . import native_image_upgrade as image, service_observer as observer
from .native_package import preflight_as_owner
from .service_restart import file_hash, file_identity

SCHEMA = "lax-native-release-upgrade/v1"
CURRENT = "native-release-current.json"


def active_spec(spec, authority, host, agent):
    root = observer.directory(authority, host, agent)
    path = root / CURRENT
    if not path.exists():
        return dict(spec)
    value = observer.protected(path)
    accepted = observer.protected(root / ("image-" + value["operationId"] + "-accepted.json"))
    intent = observer.protected(root / ("image-" + value["operationId"] + "-intent.json"))
    if (value != accepted or accepted != {**intent, "state": "accepted"} or value.get("schema") != SCHEMA
            or value.get("state") != "accepted"
            or value["scope"] != [authority, host, agent]
            or value["originalSpecDigest"] != observer.digest(spec)):
        raise ValueError("Accepted software release differs from original provisioning")
    return {**spec, "binary": value["newBinary"], "interpreter": value["newInterpreter"],
            **({"hollywoodUrl": value["newHollywoodUrl"], "federationAuthorityId": authority} if "newHollywoodUrl" in value else {}),
            **({"authorityId":authority,"hostId":host,"agentId":agent,"runtimeMode":"room-conversation","nativeHostServer":True,"nativeStateAdoption":value["transportAdoption"]["originalState"]} if "transportAdoption" in value else {})}


def runtime_spec(authority, agent):
    from .service_memory import approved_spec
    spec, receipt, global_agent = approved_spec(authority, agent)
    return active_spec(spec, authority, spec["hostId"], agent), receipt, global_agent


def closure(root):
    """Hash every protected release entry, including resolved file symlink assets."""
    root = Path(root)
    fd = image._open_directory(root)
    os.close(fd)
    rows, identities, total = [], {}, 0
    for path in sorted(root.rglob("*")):
        if len(rows) >= 20000:
            raise ValueError("Software closure entry budget exhausted")
        info = path.lstat()
        if info.st_uid != 0 or (not path.is_symlink() and info.st_mode & 0o022):
            raise PermissionError("Software closure must be administrator protected")
        relative = path.relative_to(root).as_posix()
        row = {"path": relative, "mode": info.st_mode}
        if path.is_symlink():
            target = path.resolve(strict=True)
            if target.is_dir():
                if not target.is_relative_to(root):
                    raise ValueError("External directory symlink is not an immutable closure")
                h = image._open_directory(target)
                os.close(h)
                row.update(kind="directory-link", target=os.readlink(path), resolved=str(target))
            else:
                checksum, identity = file_hash(target, 0)
                row.update(kind="file-link", target=os.readlink(path), resolved=str(target),
                           sha256=checksum, identity=identity)
                total += identity[2]
        elif path.is_dir():
            row["kind"] = "directory"
        elif path.is_file():
            checksum, identity = file_hash(path, 0)
            row.update(kind="file", sha256=checksum, identity=identity)
            total += info.st_size
        else:
            raise ValueError("Unsupported software closure entry")
        if total > 4 * 1024**3:
            raise ValueError("Software closure byte budget exhausted")
        rows.append(row)
        identities[relative] = list(image._identity(info))
    return {"root": str(root), "rootIdentity": list(image._identity(root.stat())),
            "entries": rows, "identities": identities, "bytes": total}


def probe(binary, interpreter, uid, home, release, *, service_home=None):
    owner_home=Path(service_home) if service_home is not None else home
    package = preflight_as_owner(binary, interpreter, uid, owner_home,
                                **({'workspace':home/'work'} if service_home is not None else {}))
    if set(package["assets"]) != {"entrypoint", "codeModeHost", "bubblewrap", "ripgrep"}:
        raise ValueError("Complete native package and helper proof required")
    account = pwd.getpwuid(uid)
    script = ("import json,sys,lax_connector.connector as c;"
              "print(json.dumps({'uid':__import__('os').geteuid(),"
              "'module':c.__file__,'prefix':sys.prefix}))")
    result = subprocess.run(
        ["runuser", "-u", account.pw_name, "--", str(interpreter), "-I", "-B", "-c", script],
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "HOME": str(owner_home),
             "CODEX_HOME": str(owner_home / "codex-home")},
        stdin=subprocess.DEVNULL, capture_output=True, timeout=10,
    )
    if result.returncode or len(result.stdout) > 65536:
        raise ValueError("Service-UID connector interpreter startup failed")
    value = json.loads(result.stdout)
    if (value["uid"] != uid
            or not Path(value["module"]).resolve().is_relative_to(release)
            or not Path(value["prefix"]).resolve().is_relative_to(release)):
        raise ValueError("Service interpreter loaded a different software closure")
    return {"nativePackage": package, "connector": value,
            "outputSha256": hashlib.sha256(result.stdout + result.stderr).hexdigest(),
            "modelsStarted": 0, "servicesStarted": 0}


def physical(home, uid, *, spec=None):
    result = {}
    from .shared_account import attachment
    shared=attachment(spec,home,require_receipt=True) if spec else None
    if shared and shared['account'].pw_uid!=uid:
        raise ValueError('Original shared service UID differs')
    if not shared and Path(pwd.getpwuid(uid).pw_dir) != home:
        raise ValueError("Original NSS home differs")
    paths=(home,home/'work',home/'state',Path(shared['manifest']['codexHome']),Path(shared['manifest']['state'])) if shared else (home,home/'work',home/'state',home/'codex-home')
    for path in paths:
        fd = image._open_directory(path, uid)
        try:
            info = os.fstat(fd)
            result[str(path)] = [info.st_dev, info.st_ino, info.st_uid]
        finally:
            os.close(fd)
    return result


def prepare(authority, host, agent, request, output):
    if os.geteuid() != 0:
        raise PermissionError("Verified release administrator required")
    authority, host, agent = [str(UUID(v)) for v in (authority, host, agent)]
    scope = [authority, host, agent]
    root = observer.directory(*scope)
    from .service_memory import approved_spec
    from .service_restart import settled_definitions
    from .collaboration_install import protected_tree
    with image.registry_lock(root) as fd:
        image.require_settled_transition(fd)
        settled_definitions(root)
        old = image._json(fd, "enrollment.json")
        spec, _, _ = approved_spec(authority, agent)
        uid, home, _ = observer.expected_owner(authority, agent)
        home = Path(home)
        from .shared_account import attachment
        shared=attachment(spec,home,require_receipt=True)
        if shared and 'sharedNativeUpgrade' in request:
            raise PermissionError('Only the original host owner can coordinate a shared engine release')
        config_path = home / "connector.json"
        config_bytes = config_path.read_bytes()
        config_hash, _ = file_hash(config_path, uid)
        info = observer.properties(observer.installed_unit(authority, agent))
        unit_path = Path(info["FragmentPath"])
        definition = observer.unit_definition(info)
        before_unit = unit_path.read_bytes()
        if (observer.digest(old) != request["expectedEnrollment"]
                or config_hash != request["expectedConfigurationSha256"]
                or definition != request["expectedDefinition"]
                or hashlib.sha256(config_bytes).hexdigest() != config_hash
                or hashlib.sha256(before_unit).hexdigest() != definition):
            raise ValueError("Original enrollment/configuration/unit CAS changed")
        enrolled_image = Path(old["binary"]).stat()
        if (enrolled_image.st_dev, enrolled_image.st_ino) != (old["binaryDevice"], old["binaryInode"]):
            raise ValueError("Original enrolled native image identity changed")
        config = json.loads(config_bytes)
        old_root, new_root = [Path(request[k]) for k in ("oldReleaseRoot", "newReleaseRoot")]
        old_binary, new_binary = [Path(request[k]) for k in ("oldBinary", "newBinary")]
        old_python, new_python = [Path(request[k]) for k in ("oldInterpreter", "newInterpreter")]
        retained_native = None
        if 'retainNativeImage' in request:
            if (request['retainNativeImage'] is not True or not config.get('nativeServer')
                    or config.get('runtimeMode') != 'room-conversation' or old_binary != new_binary
                    or any(k in request for k in ('sharedNativeUpgrade','newNativeServer'))
                    or request.get('newConversationDynamicTools', config.get('conversationDynamicTools')) != config.get('conversationDynamicTools')):
                raise ValueError('Connector-only native dependency must retain the exact shared image and bindings')
            from .native_dependency import capture
            retained_native = capture(config)
        paths = [(old_python, old_root), (new_python, new_root)]
        if retained_native is None:
            paths += [(old_binary, old_root), (new_binary, new_root)]
        elif any(not p.is_absolute() or '..' in p.parts or not re.fullmatch(r"/[A-Za-z0-9_./+-]+",str(p)) for p in (old_binary,new_binary)):
            raise ValueError('Literal unchanged native image paths required')
        for path, release in paths:
            if (not path.is_absolute() or ".." in path.parts or not path.is_relative_to(release)
                    or not re.fullmatch(r"/[A-Za-z0-9_./+-]+", str(path))):
                raise ValueError("Exact old/new paths must belong to their reviewed release and be literal unit paths")
        if old_root == new_root or old_root.is_relative_to(new_root) or new_root.is_relative_to(old_root):
            raise ValueError("Distinct nonnested immutable release paths required")
        h = image._open_directory(old_root)
        os.close(h)
        file_identity(old_binary)
        h = image._open_directory(old_python.parent)
        os.close(h)
        if old_python.lstat().st_uid != 0:
            raise PermissionError("Original interpreter path is not root owned")
        if str(old_binary.resolve(strict=True)) != str(old_binary):
            raise ValueError("Native entrypoints must be exact nonsymlink paths")
        if str(new_binary.resolve(strict=True)) != str(new_binary):
            raise ValueError("New native entrypoint must be an exact nonsymlink path")
        before_exec = f"ExecStart={old_python} -m lax_connector.connector --config {config_path} --serve"
        after_exec = f"ExecStart={new_python} -m lax_connector.connector --config {config_path} --serve"
        if (config["binary"] != str(old_binary)
                or config["agentId"] != agent or config["hostId"] != host
                or config["state"] != str(home / "state")
                or config["workspace"] != str(home / "work")
                or config["codexHome"] != (shared['manifest']['codexHome'] if shared else str(home / "codex-home"))
                or before_unit.decode().splitlines().count(before_exec) != 1
                or len(re.findall(r"(?m)^ExecStart=", before_unit.decode())) != 1):
            raise ValueError("Reviewed original connector/ExecStart identity differs")
        software = closure(new_root)
        probes = probe(new_binary, new_python, uid, home, new_root,
                       **({'service_home':Path(shared['identity']['serviceHome'])} if shared else {}))
        if retained_native is not None:
            from .native_dependency import pin_package, verify
            retained_native = pin_package(retained_native, probes['nativePackage'])
            if probes['nativePackage']['assets']['entrypoint']['sha256'] != retained_native['imageSha256']:
                raise ValueError('Accepted native image changed during connector qualification')
            verify(retained_native, config)
        elif not Path(probes["nativePackage"]["packageRoot"]).is_relative_to(new_root):
            raise ValueError("Native package escaped new release")
        if closure(new_root) != software:
            raise ValueError("Release changed during actual service-UID startup")
        if config_path.read_bytes() != config_bytes or unit_path.read_bytes() != before_unit:
            raise ValueError("Original configuration/unit changed during review")
        new_values = {**config, "binary": str(new_binary)}
        if shared and not os.path.samefile(new_binary,shared['manifest']['binary']):
            raise ValueError('Attached connector release must retain the accepted shared native image; coordinated engine release required')
        transport_probe=None
        shared_upgrade=None
        shared_targets=[]
        if 'sharedNativeUpgrade' in request:
            expected=request['sharedNativeUpgrade']
            if (not config.get('nativeServer') or 'newNativeServer' in request
                    or not isinstance(expected,dict)
                    or set(expected)!={'expectedManifestSha256','expectedDefinition'}):
                raise ValueError('Exact existing shared engine upgrade pins required')
            from .shared_native_release import prepare as prepare_shared
            shared_upgrade,shared_targets=prepare_shared(config,new_values,
                expected['expectedManifestSha256'],expected['expectedDefinition'])
        if 'newNativeServer' in request:
            if config.get('nativeServer') is not None:
                raise ValueError('Existing transport changes require a separate original-owner migration')
            from .rpc_shared import host_manifest
            selected=request['newNativeServer']
            candidate={**new_values,'nativeServer':selected}
            host_value=host_manifest(candidate)
            if (host_value.get('ownerAgentId')!=agent
                    or host_value.get('adoptedNativeThreadId')!=config.get('nativeThreadId')
                    or host_value.get('adoptedConfigurationSha256')!=config_hash
                    or host_value['state']!=str(home/'state/native')):
                raise ValueError('Host daemon must adopt the exact original context and native storage')
            if config.get('runtimeMode')!='room-conversation':
                raise ValueError('Historical delivery journals can only remain observational in existing conversation mode')
            transport_read=transport_inspect(new_python,uid,config_path,selected['manifest'])
            from .host import request as host_request
            pending=host_request(config['hollywoodUrl'],config['token'],'GET','connector/pending?hostId='+host)
            historical_unknown=pending.get('busy')
            if historical_unknown is not None and (historical_unknown.get('state')!='unknown'
                    or historical_unknown.get('native_thread')!=config['nativeThreadId']):
                raise ValueError('Only an unchanged historical unknown on this original context may be preserved')
            new_values['nativeServer']=selected
            transport_probe={'historicalUnknown':historical_unknown,'nativeRead':transport_read,'nativeServer':selected,'nativeThreadId':config['nativeThreadId'],
                             'nativeState':host_value['state'],'profileUnchanged':True,
                             'originalState':{'state':host_value['state'],'nativeThreadId':config['nativeThreadId'],'configurationSha256':config_hash}}
        elif config.get('nativeServer'):
            from .rpc_shared import host_manifest
            selected=config['nativeServer'];host_value=host_manifest(config if shared_upgrade else {**new_values,'nativeServer':selected})
            if host_value.get('ownerAgentId')!=(shared['identity']['ownerAgentId'] if shared else agent):
                raise ValueError('Original host transport owner changed')
            transport_read=transport_inspect(new_python,uid,config_path,selected['manifest'],
                                             **({'shared_client':True, **({'allow_terminal_failure':True} if retained_native is not None else {})} if not shared_upgrade else {}))
            from .host import request as host_request
            pending=host_request(config['hollywoodUrl'],config['token'],'GET','connector/pending?hostId='+host)
            historical_unknown=pending.get('busy')
            if historical_unknown is not None and (historical_unknown.get('state')!='unknown'
                    or historical_unknown.get('native_thread')!=config['nativeThreadId']):
                raise ValueError('Active original delivery must be drained before release')
            original_state=({'state':host_value['state'],'nativeThreadId':host_value['adoptedNativeThreadId'],
                             'configurationSha256':host_value['adoptedConfigurationSha256']}
                            if not shared and 'adoptedNativeThreadId' in host_value else None)
            transport_probe={'historicalUnknown':historical_unknown,'nativeRead':transport_read,
                'nativeServer':selected,'nativeThreadId':config['nativeThreadId'],
                'nativeState':host_value['state'],'profileUnchanged':True,'originalState':original_state}
        if 'newConversationDynamicTools' in request:
            from .room_tools import TOOLS
            if (transport_probe is None or config.get('runtimeMode')!='room-conversation'
                    or request['newConversationDynamicTools']!=TOOLS):
                raise ValueError('Only the exact reviewed conversational tool declarations may be installed at an idle host boundary')
            new_values['conversationDynamicTools']=TOOLS
        instruction_adoption = None
        if 'newConversationInstructionAdoption' in request:
            if transport_probe is None or shared_upgrade or 'newNativeServer' in request:
                raise ValueError('Instruction adoption needs the unchanged original shared native transport')
            from .room_participation import release_patch
            patch, instruction_adoption = release_patch(config,
                request['newConversationInstructionAdoption'], scope, config_hash)
            new_values.update(patch)
        route_probe = None
        if 'newHollywoodUrl' in request or 'expectedHollywoodUrl' in request:
            from urllib.parse import urlsplit
            from urllib.request import Request, urlopen
            new_url = request['newHollywoodUrl']
            target = urlsplit(new_url)
            if (config['hollywoodUrl'] != request['expectedHollywoodUrl']
                    or target.scheme != 'http' or target.hostname not in {'127.0.0.1','::1'}
                    or target.username is not None or target.password is not None
                    or target.path or target.query or target.fragment
                    or target.port is None or not 1 <= target.port <= 65535):
                raise ValueError('Reviewed host-local Hollywood route differs')
            # Metadata-only existing agent read; no model, claim or new input.
            headers = {'Authorization':'Bearer '+config['token'],
                'X-Hollywood-Authority':authority,'X-Hollywood-Agent':agent}
            with urlopen(Request(new_url+'/hollywood/v3/rooms',headers=headers),timeout=5) as response:
                catalog=json.load(response)
            if catalog.get('authorityId') != authority or not isinstance(catalog.get('rooms'),list):
                raise ValueError('Host-local route did not return original canonical authority')
            route_probe={'url':new_url,'authorityId':authority,'modelsStarted':0,
                'authenticatedOriginalAgentRead':True}
            new_values['hollywoodUrl']=new_url
            new_values['federationAuthorityId']=authority
        new_config = (json.dumps(new_values, indent=2) + "\n").encode()
        new_unit = "\n".join(after_exec if line == before_exec else line
                             for line in before_unit.decode().split("\n")).encode()
        image_info = new_binary.stat()
        upgraded = {**old, "binary": str(new_binary),
                    "binaryDevice": image_info.st_dev, "binaryInode": image_info.st_ino,
                    "unitDefinitionDigest": hashlib.sha256(new_unit).hexdigest()}
        physical_paths = physical(home, uid,**({'spec':spec} if shared else {}))
        targets = []
        for path, before, after, owner in (
                (config_path, config_bytes, new_config, uid),
                (unit_path, before_unit, new_unit, 0)):
            targets.append({"path": str(path), "uid": owner,
                            "mode": path.stat().st_mode & 0o777,
                            "before": base64.b64encode(before).decode(),
                            "after": base64.b64encode(after).decode()})
        if shared_upgrade:shared_upgrade["targets"]=shared_targets
        prepared = {**({"sharedNativeUpgrade":shared_upgrade} if shared_upgrade else {}),"schema": SCHEMA, "scope": scope, "state": "prepared",
                    "originalSpecDigest": observer.digest(spec), "priorEnrollment": old,
                    "approvedEnrollment": upgraded, "physical": physical_paths,
                    "unit": info["Id"], "home": str(home), "uid": uid,
                    "oldReleaseRoot": str(old_root), "newReleaseRoot": str(new_root),
                    "oldRootIdentity": list(image._identity(old_root.stat())),
                    "oldBinary": str(old_binary), "newBinary": str(new_binary),
                    "oldInterpreter": str(old_python), "newInterpreter": str(new_python),
                    **({"oldHollywoodUrl":config['hollywoodUrl'],"newHollywoodUrl":new_values['hollywoodUrl'],
                        "routeProbe":route_probe} if route_probe is not None else {}),
                    "oldImageSha256": file_hash(old_binary, 0)[0],
                    "oldInterpreterIdentity": file_identity(old_python.resolve()),
                    "closure": software, "probes": probes, "targets": targets,
                    **({"transportAdoption":transport_probe} if transport_probe else {}),
                    **({"instructionAdoption":instruction_adoption} if instruction_adoption else {}),
                    "imageIdentity": list(image._identity(image_info)),
                    "approvedImageSha256": probes["nativePackage"]["assets"]["entrypoint"]["sha256"],
                    "unitDefinitionDigest": upgraded["unitDefinitionDigest"],
                    "modelsStarted": 0, "servicesStarted": 0, "executionReady": False}
        if shared:prepared['sharedAgentIdentity']=shared['identity']
        if retained_native is not None:prepared['retainedNative']=retained_native
        if Path(output).is_relative_to(new_root) or Path(output).is_relative_to(home):
            raise ValueError("Review output cannot modify release or private state")
        target = protected_tree(output, 0o700)
        target_fd = image._open_directory(target)
        try:
            image._write(target_fd, "release-plan.json", prepared)
        finally:
            os.close(target_fd)
        return {"prepared": str(target / "release-plan.json"),
                "preparationDigest": observer.digest(prepared), "scope": scope,
                "closureDigest": observer.digest(software),
                "newConfigurationSha256": hashlib.sha256(new_config).hexdigest(),
                **({"instructionAdoption":instruction_adoption} if instruction_adoption else {}),
                **({"oldHollywoodUrl":config['hollywoodUrl'],"newHollywoodUrl":new_values['hollywoodUrl'],
                    "routeProbe":route_probe} if route_probe is not None else {}),
                "newDefinitionSha256": hashlib.sha256(new_unit).hexdigest(),
                "probes": probes, "modelsStarted": 0, "servicesStarted": 0}


def transport_inspect(interpreter,uid,config_path,manifest,*,shared_client=False,allow_terminal_failure=False):
    account=pwd.getpwuid(uid)
    result=subprocess.run(['runuser','-u',account.pw_name,'--',str(interpreter),'-I','-B',
        '-m','lax_connector.transport_adoption',str(config_path),str(manifest),*(['--existing-client'] if shared_client else []),*(['--allow-terminal-failure'] if allow_terminal_failure else [])],
        stdin=subprocess.DEVNULL,capture_output=True,timeout=15)
    if result.returncode or len(result.stdout)>8192:
        raise ValueError('Original native context read failed; retain transport migration held')
    return json.loads(result.stdout)


def identity_arguments(plan):
    """Revalidate new shared layouts; legacy accepted plans remain unchanged."""
    if 'sharedAgentIdentity' not in plan:return {},{}
    from .service_memory import approved_spec
    from .shared_account import attachment
    authority,host,agent=plan['scope'];spec,_,_=approved_spec(authority,agent)
    shared=attachment(spec,Path(plan['home']),require_receipt=True)
    if (observer.digest(spec)!=plan['originalSpecDigest'] or not shared
            or shared['identity']!=plan['sharedAgentIdentity'] or shared['account'].pw_uid!=plan['uid']):
        raise ValueError('Original shared release enrollment differs')
    return {'spec':spec},{'service_home':Path(shared['identity']['serviceHome'])}
