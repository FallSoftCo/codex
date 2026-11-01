"""Real Windows native-socket/WebSocket and fail-before-send qualification."""
import asyncio,ctypes,json,os,pathlib,socket,sys,threading,subprocess,hashlib
import argparse
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--evidence',type=pathlib.Path,required=True);args=parser.parse_args()
ROOT=args.evidence
if os.name!='nt':raise SystemExit('This integration requires a real Windows host')
from aiohttp import ClientSession,web
from lax_connector import windows_ipc as platform_ipc
from lax_connector import conversational_agent,room_bootstrap,room_entry,journal,runtime_files

result=ROOT/'result.json'
assert not ROOT.exists(),'Inspect the original qualification directory instead of replaying'
platform_ipc.create_private_directory(ROOT)
private=ROOT/'private';path=private/'native.sock'
assert not private.exists(),'Retain original uncertain fixture state'
platform_ipc.create_private_directory(private)
ws=ctypes.WinDLL('Ws2_32',use_last_error=True);HANDLE=ctypes.c_size_t;INVALID=HANDLE(-1).value
ws.WSASocketW.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_void_p,ctypes.c_ulong,ctypes.c_ulong];ws.WSASocketW.restype=HANDLE
ws.bind.argtypes=[HANDLE,ctypes.c_void_p,ctypes.c_int];ws.bind.restype=ctypes.c_int
ws.listen.argtypes=[HANDLE,ctypes.c_int];ws.listen.restype=ctypes.c_int
ws.accept.argtypes=[HANDLE,ctypes.c_void_p,ctypes.c_void_p];ws.accept.restype=HANDLE
ws.closesocket.argtypes=[HANDLE];ws.WSAGetLastError.restype=ctypes.c_int
class Address(ctypes.Structure):_fields_=[('family',ctypes.c_ushort),('path',ctypes.c_char*108)]
def check(value):
 if value==-1:raise OSError(ws.WSAGetLastError(),'Winsock fixture error')
 return value
listener=None;thread=None;server_errors=[];accepted=[];http_requests=[];scheduled=[]
def file_checks():
 runtime_files.state_directory(private/'nested/receipts',parents=True,exist_ok=True)
 platform_ipc.private_path(private/'nested',directory=True)
 platform_ipc.private_path(private/'nested/receipts',directory=True)
 unsafe=private/'posix-mode';unsafe.mkdir(mode=0o700)
 try:runtime_files.state_directory(unsafe,exist_ok=True)
 except PermissionError:pass
 else:raise AssertionError('Unsafe existing state ACL was silently accepted')
 from uuid import uuid4
 from lax_connector.room_subscriptions import RoomSubscriptions
 subscriptions=RoomSubscriptions(state=private/'subscriptions',authority=str(uuid4()),agent=str(uuid4()),thread='fixture-thread',rooms=[{'roomId':str(uuid4()),'after':0}],request=None,create=None,on_rooms=lambda rooms:None)
 subscriptions.persist()
 assert (private/'subscriptions/memberships.json').is_file()
 path=private/'nested/receipts/operation.json'
 journal.saved(path,{'operationId':'fixture-original-232','state':'pending'})
 journal.saved(path,{'operationId':'fixture-original-232','state':'accepted'})
 assert json.loads(path.read_text())=={'operationId':'fixture-original-232','state':'accepted'}
 runtime_files.private_file(path)
 lock=private/'connector.lock'
 code="import sys;sys.path.insert(0,sys.argv[1]);from lax_connector.runtime_files import exclusive_lock;f=open(sys.argv[2],'a')\ntry:exclusive_lock(f)\nexcept OSError:sys.exit(37)\n"
 args=[sys.executable,'-I','-c',code,str(pathlib.Path(runtime_files.__file__).parent.parent),str(lock)]
 with lock.open('a') as held:
  runtime_files.exclusive_lock(held)
  blocked=subprocess.run(args,capture_output=True,timeout=5)
  assert blocked.returncode==37,(blocked.returncode,blocked.stderr.decode())
 released=subprocess.run(args,capture_output=True,timeout=5)
 assert released.returncode==0,(released.returncode,released.stderr.decode())
 assert len(runtime_files.machine_identity())==64
 return {'durableReceiptReopen':True,'originalOperationIdPreserved':True,'exclusiveCrossProcessLock':True,'releaseAllowsSuccessor':True,'shortQaChildProcesses':2,'candidateImportWindows':True,'nestedStateDirectoriesPrivate':True,'actualRoomSubscriptionsPersisted':True,'unsafeExistingStateRejected':True,'moduleSha256':hashlib.sha256(pathlib.Path(platform_ipc.__file__).read_bytes()).hexdigest()}

async def main():
 global listener,thread
 files=file_checks()
 app=web.Application()
 async def echo(request):
  http_requests.append(request.method)
  channel=web.WebSocketResponse();await channel.prepare(request)
  value=await channel.receive_json();await channel.send_json({'echo':value});await channel.close();return channel
 app.router.add_get('/',echo);runner=web.AppRunner(app,tcp_keepalive=False);await runner.setup();loop=asyncio.get_running_loop()
 listener=ws.WSASocketW(1,1,0,None,0,1);assert listener!=INVALID
 address=Address(1,os.fsencode(path));check(ws.bind(listener,ctypes.byref(address),ctypes.sizeof(address)));check(ws.listen(listener,4))
 def serve():
  try:
   for _ in range(3):
    raw=ws.accept(listener,None,None)
    if raw==INVALID:raise OSError(ws.WSAGetLastError(),'accept failed')
    peer=socket.socket(1,1,0,fileno=raw);peer.setblocking(False);accepted.append(raw)
    scheduled.append(asyncio.run_coroutine_threadsafe(loop.connect_accepted_socket(runner.server,peer),loop))
  except Exception as e:server_errors.append(repr(e))
 thread=threading.Thread(target=serve,daemon=True);thread.start()
 try:
  async with ClientSession(connector=platform_ipc.WindowsUnixConnector(path,sys.executable)) as client:
   async with client.ws_connect('http://localhost/') as channel:
    await channel.send_json({'message':'bounded Windows IPC qualification'});reply=await channel.receive_json()
    assert reply=={'echo':{'message':'bounded Windows IPC qualification'}},reply
  rejects=[]
  for name,binary,pid in [('wrong-pid',sys.executable,os.getpid()+1),('wrong-image',str(pathlib.Path(os.environ['SystemRoot'])/'System32/cmd.exe'),None)]:
   try:
    unexpected=await asyncio.to_thread(platform_ipc._authenticated_socket,path,binary,expected_pid=pid)
   except PermissionError:rejects.append(name)
   else:unexpected.close();raise AssertionError('Unexpected peer accepted: '+name)
  try:platform_ipc.private_path(private/'posix-mode',directory=True)
  except PermissionError:rejects.append('inherited-dacl')
  else:raise AssertionError('Unprotected directory accepted')
  await asyncio.to_thread(thread.join,3)
  assert not thread.is_alive() and not server_errors,server_errors
  for task in scheduled:await asyncio.wrap_future(task)
  await asyncio.sleep(.1)
  assert len(accepted)==3 and http_requests==['GET'],{'accepted':len(accepted),'requests':http_requests}
  return {'passed':True,'files':files,'websocketEcho':True,'kernelAuthenticatedNativeUnixSocket':True,'rejectedBeforeHttpBytes':rejects,'acceptedSocketConnections':len(accepted),'httpRequests':len(http_requests),'codexProcessesStarted':0,'servicesChanged':0,'credentialsRead':False}
 finally:await runner.cleanup()
try:out=asyncio.run(asyncio.wait_for(main(),20))
except BaseException as e:out={'passed':False,'errorType':type(e).__name__,'error':str(e),'serverErrors':server_errors,'accepted':len(accepted),'requests':len(http_requests),'credentialsRead':False}
finally:
 if listener is not None:ws.closesocket(listener)
 if thread is not None:thread.join(2)
 path.unlink(missing_ok=True)
 result.write_text(json.dumps(out,indent=2));print(json.dumps(out))
