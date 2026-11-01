"""Install/control explicitly named LAX Windows desktop-user tasks.

No polling, credential-based logon, implicit startup or replacement enrollment.
Task Scheduler supplies one bounded crash restart policy; explicit stops and
ambiguous original starts remain stopped until an owning control action.
"""
import hashlib,json,pathlib,sys,time
from lax_connector.journal import saved
from lax_connector.runtime_files import private_file


def definition_identity(definition):
    import ntpath
    import win32security
    def sid(value):
        identity=(win32security.ConvertStringSidToSid(value) if value.startswith('S-')
                  else win32security.LookupAccountName(None,value)[0])
        return win32security.ConvertSidToStringSid(identity)
    settings=definition.Settings
    return {'principal':{'userId':sid(definition.Principal.UserId),'logonType':definition.Principal.LogonType,'runLevel':definition.Principal.RunLevel},
            'actions':[{'type':a.Type,'path':ntpath.normcase(ntpath.normpath(a.Path)),'arguments':a.Arguments,'cwd':ntpath.normcase(ntpath.normpath(a.WorkingDirectory))} for a in definition.Actions],
            'triggers':[{'type':t.Type,'userId':sid(t.UserId),'enabled':t.Enabled} for t in definition.Triggers],
            'settings':{name:getattr(settings,name) for name in ('MultipleInstances','ExecutionTimeLimit','DisallowStartIfOnBatteries','StopIfGoingOnBatteries','RestartInterval','RestartCount','StartWhenAvailable','Hidden')}}


def install(spec_path):
    import win32api,win32con,win32security,win32com.client
    private_file(spec_path)
    spec=json.loads(pathlib.Path(spec_path).read_text())
    assert spec['schema']=='lax-windows-task/v1'
    assert spec['role'] in ('postgres','hollywood','native','global')
    name=spec['taskName']
    assert name.startswith('LaxHost-') and all(c.isalnum() or c=='-' for c in name)
    command=spec['command']
    assert command and pathlib.Path(command[0]).name.lower()=='pythonw.exe'
    assert pathlib.Path(command[0]).is_absolute() and pathlib.Path(spec['cwd']).is_absolute()
    token=win32security.OpenProcessToken(win32api.GetCurrentProcess(),win32con.TOKEN_QUERY)
    try:
        assert not win32security.GetTokenInformation(token,win32security.TokenElevation)
        assert win32security.GetTokenInformation(token,win32security.TokenSessionId)==1
        user=win32security.ConvertSidToStringSid(win32security.GetTokenInformation(token,win32security.TokenUser)[0])
    finally:token.Close()
    directory=pathlib.Path(spec['recordDirectory'])
    from lax_connector.windows_ipc import private_path
    private_path(directory,directory=True)
    digest=hashlib.sha256(json.dumps(spec,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    service=win32com.client.Dispatch('Schedule.Service');service.Connect();folder=service.GetFolder('\\')
    definition=service.NewTask(0)
    definition.RegistrationInfo.Description='LAX '+spec['role']+'; limited interactive user, one host runtime, no polling'
    definition.Principal.UserId=user;definition.Principal.LogonType=3;definition.Principal.RunLevel=0
    settings=definition.Settings
    settings.MultipleInstances=2;settings.ExecutionTimeLimit='PT0S'
    settings.DisallowStartIfOnBatteries=False;settings.StopIfGoingOnBatteries=False
    settings.RestartInterval='PT1M';settings.RestartCount=3
    settings.StartWhenAvailable=False;settings.Hidden=True
    trigger=definition.Triggers.Create(9);trigger.UserId=user;trigger.Enabled=True
    action=definition.Actions.Create(0)
    import subprocess
    action.Path=command[0];action.Arguments=subprocess.list2cmdline(command[1:]);action.WorkingDirectory=spec['cwd']
    expected=definition_identity(definition)
    definition_digest=hashlib.sha256(json.dumps(expected,sort_keys=True).encode()).hexdigest()
    found=[task for task in folder.GetTasks(1) if task.Name==name]
    record=directory/'installation.json'
    if found:
        prior=json.loads(record.read_text())
        assert prior['specSha256']==digest and definition_identity(found[0].Definition)==expected,'Existing task definition differs'
        # Task Scheduler rewrites XML when Enabled changes. Preserve that
        # operational stop independently from the actual execution definition.
        saved(directory/'definition-reconciliation.json',{'definitionSha256':definition_digest,'observedXmlSha256':hashlib.sha256(found[0].Xml.encode()).hexdigest(),'originalInstallationRetained':True,'enabled':found[0].Enabled,'time':time.time()})
        return {**prior,'definitionSha256':definition_digest,'reconciled':True,'taskState':found[0].State,'enabled':found[0].Enabled,'started':False}
    assert not (directory/'installation-intent.json').exists(),'Reconcile original registration before retry'
    saved(directory/'installation-intent.json',{'taskName':name,'specSha256':digest,'definitionSha256':definition_digest,'time':time.time()})
    task=folder.RegisterTaskDefinition(name,definition,2,user,None,3)
    assert definition_identity(task.Definition)==expected,'Registered execution definition differs'
    out={'taskName':name,'specSha256':digest,'definitionSha256':definition_digest,'xmlSha256':hashlib.sha256(task.Xml.encode()).hexdigest(),'userSidSha256':hashlib.sha256(user.encode()).hexdigest(),'installedAt':time.time(),'logonType':'InteractiveToken','runLevel':'LeastPrivilege','started':False}
    saved(record,out);return out


def start_once(spec_path):
    import win32com.client
    private_file(spec_path);spec=json.loads(pathlib.Path(spec_path).read_text())
    prior=install(spec_path)
    service=win32com.client.Dispatch('Schedule.Service');service.Connect();task=service.GetFolder('\\').GetTask(spec['taskName'])
    assert task.Enabled,'Deliberately disabled task must not be implicitly restarted'
    if task.State==4:return {**prior,'alreadyRunning':True,'started':False}
    directory=pathlib.Path(spec['recordDirectory']);intent=directory/'start-intent.json'
    assert not intent.exists(),'Original startup must be reconciled; no implicit restart'
    saved(intent,{'taskName':spec['taskName'],'time':time.time()})
    instance=task.Run(None)
    out={'taskName':spec['taskName'],'instanceGuid':instance.InstanceGuid,'submittedAt':time.time(),'started':True,'modelsRequestedByControl':0}
    saved(directory/'start-result.json',out);return out


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('install','start'));parser.add_argument('--spec',required=True,type=pathlib.Path)
    args=parser.parse_args();print(json.dumps((install if args.action=='install' else start_once)(args.spec)))
