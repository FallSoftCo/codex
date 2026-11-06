"""Read-only validation for a stopped parent's existing-context role handover.

This is NOT live admission and cannot initialize or run a logical session. The
caller holds the original parent/child connector locks. The OS task, terminated
original parent and separately accepted owner closure are checked independently;
normal resident startup retains the live-parent validation path.
"""
import hashlib,json,subprocess
from pathlib import Path
from . import room_factory_windows_state as platform
from .windows_ipc import private_path

def inspect_stopped_parent(policy_path,*,expected_policy_sha256):
 import win32api,win32con,win32event,win32com.client
 owner=platform.current_owner();p=platform.read(policy_path,expected_policy_sha256)
 platform.require(p.get('schema')=='lax-windows-room-parent-policy/v2','Explicit original Windows v2 policy required')
 platform.require(p['ownerSidSha256']==platform.digest(owner.encode()),'Original maintenance account differs')
 a=platform.read_parent_acceptance(p,expected_policy_sha256=expected_policy_sha256)
 platform.require(a.get('state')=='running'and a.get('admissionAllowed')is False,'Separately owner-closed admission required for role maintenance')
 op=Path(a['ownerAcceptanceOperationId']);private_path(op,directory=True)
 intent=platform.read(op/'intent.json');accepted=platform.read(op/'accepted.json');intended=platform.read(op/'intended.private.json');original=platform.read(op/'original.private.json');review=platform.read(op/'review.private.json')
 locator=Path(p['parentAcceptanceLocator']['path']);raw=locator.read_bytes()
 platform.require(intent['mode']=='close-successor'and accepted['mode']=='close-successor'and accepted['state']=='accepted'
  and intent['target']==str(locator)and intent['intendedSha256']==platform.digest(raw)==accepted['locatorSha256']
  and a==intended and original.get('admissionAllowed')is True
  and all(a[k]==original[k]for k in ('runtimeIdentity','nativeIdentity','policySha256','parentArgvSha256')),
  'Original separately accepted owner closure differs')
 # The locator retains a canonical JSON review copy. Its bytes deliberately
 # differ from the external review file whose original hash is in the intent.
 # Compare the stored review semantics and bound pins, not serializer bytes.
 platform.require(review.get('approved')is True and review.get('mode')=='close-successor'
  and review['expectedPins']==intent['pins']
  and intent['pins']['runtimeIdentity']==a['runtimeIdentity']and intent['pins']['nativeIdentity']==a['nativeIdentity']
  and intent['pins']['policySha256']==expected_policy_sha256,'Closure owner review differs')
 # A failed query is not proof of a stopped process: only a signaled original
 # process handle or Windows ERROR_INVALID_PARAMETER for an absent PID qualifies.
 try:h=win32api.OpenProcess(win32con.SYNCHRONIZE|win32con.PROCESS_QUERY_LIMITED_INFORMATION,False,a['runtimeIdentity']['pid'])
 except Exception as error:
  platform.require(getattr(error,'winerror',None)==87,'Original parent termination is unavailable, not proven')
 else:
  try:platform.require(win32event.WaitForSingleObject(h,0)==win32event.WAIT_OBJECT_0,'Original parent is still running; role handover refused')
  finally:h.Close()
 service=win32com.client.Dispatch('Schedule.Service');service.Connect();task=service.GetFolder('\\').GetTask(p['parentTaskName']);d=task.Definition
 platform.require(task.Enabled and task.State==3 and task.GetInstances(0).Count==0,'Original task must remain enabled and stopped/Ready')
 platform.require(_sid(d.Principal.UserId)==owner,'Original task owner differs')
 platform.require(d.Principal.LogonType==3 and d.Principal.RunLevel==0 and d.Actions.Count==1 and d.Actions.Item(1).Type==0,'Original limited dedicated task required')
 action=d.Actions.Item(1);argv=platform.argv(subprocess.list2cmdline([action.Path])+' '+action.Arguments)
 platform.require(platform.argv_digest(argv)==a['parentArgvSha256'],'Stopped task command differs from accepted original process')
 metadata=platform.read(p['parentRuntimeMetadata']);platform.require(metadata['pid']==a['runtimeIdentity']['pid'],'A different parent incarnation has been started')
 root=Path(p['agentRoot']);private_path(root,directory=True)
 manifest=platform.read(p['nativeHostManifest'],p['nativeHostManifestSha256'])
 platform.require(manifest['schema']=='lax-native-host/v1'and manifest['platform']=='windows'and manifest['runtimeMode']=='room-conversation'
  and all(manifest[k]==p[k]for k in ('authorityId','hostId'))and manifest['ownerAgentId']==p['parentAgentId'],'Original shared native binding differs')
 platform.require(all(not root.is_relative_to(Path(manifest[k]))for k in ('codexHome','state'))and root!=Path(manifest['workspace']),'Agent root overlaps original native state/profile')
 peer=platform.native_peer(manifest);platform.require(peer==a['nativeIdentity'],'Original shared native incarnation changed')
 return {'schema':'lax-windows-parent-maintenance-evidence/v1','state':'stopped-for-role-maintenance','parentRuntime':a['runtimeIdentity'],
  'sharedNative':peer,'policySha256':expected_policy_sha256,'ownerClosureSha256':platform.digest(raw),'newProcesses':0,'modelCalls':0}

def _sid(value):
 import win32security
 return win32security.ConvertSidToStringSid(win32security.LookupAccountName(None,value)[0])if not value.startswith('S-1-')else value
