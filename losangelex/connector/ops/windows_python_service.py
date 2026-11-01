"""Run the enrolled Python service in this process with private logs and a cap."""
import argparse,json,logging,os,pathlib,runpy,sys,time,traceback
from lax_connector.journal import saved
from lax_connector.runtime_files import exclusive_lock,private_file
from lax_connector.windows_ipc import private_path

parser=argparse.ArgumentParser();parser.add_argument('--role',choices=('hollywood','global'),required=True);parser.add_argument('--config',type=pathlib.Path,required=True);parser.add_argument('--state',type=pathlib.Path,required=True);args=parser.parse_args()
private_file(args.config);private_path(args.state,directory=True)
import win32api,win32con,win32job,win32security
token=win32security.OpenProcessToken(win32api.GetCurrentProcess(),win32con.TOKEN_QUERY)
assert not win32security.GetTokenInformation(token,win32security.TokenElevation)
assert win32security.GetTokenInformation(token,win32security.TokenSessionId)==1
token.Close()
job=win32job.CreateJobObject(None,'')
limits=win32job.QueryInformationJobObject(job,win32job.JobObjectExtendedLimitInformation)
limits['BasicLimitInformation']['LimitFlags']=win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY
limits['ProcessMemoryLimit']=512*1024**2
win32job.SetInformationJobObject(job,win32job.JobObjectExtendedLimitInformation,limits)
win32job.AssignProcessToJobObject(job,win32api.GetCurrentProcess())
with (args.state/'python.lock').open('a') as lock,(args.state/'process.log').open('a',encoding='utf-8',buffering=1) as log:
    exclusive_lock(lock);sys.stdout=sys.stderr=log
    logging.basicConfig(stream=log,level=logging.INFO,force=True)
    saved(args.state/'python.json',{'role':args.role,'pid':os.getpid(),'state':'running','time':time.time()})
    status=0
    try:
        if args.role=='hollywood':
            config=json.loads(args.config.read_text())
            sys.argv=['hollywood-node','--database-config',config['databaseConfig'],'--port','19431','--federation-config',config['federationConfig']]
            runpy.run_module('hollywood_backbone.server',run_name='__main__')
        else:
            sys.argv=['lax-connect-room','--config',str(args.config),'--serve']
            runpy.run_module('lax_connector.room_entry',run_name='__main__')
    except BaseException as error:
        if not isinstance(error,SystemExit) or error.code not in (None,0):
            status=1;traceback.print_exc()
    finally:
        saved(args.state/'python.json',{'role':args.role,'pid':os.getpid(),'state':'stopped','exitCode':status,'time':time.time()})
sys.exit(status)
