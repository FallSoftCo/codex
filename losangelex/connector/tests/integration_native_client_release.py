"""SDK boundary data/dispatch journey; native transport/filesystem are not simulated as proof."""
import base64,json
from uuid import uuid4
from unittest.mock import patch
from lax_connector import native_client_release as n,native_image_upgrade as image

def main():
 authority,host,agent=[str(uuid4())for _ in range(3)]
 c={'authorityId':authority,'hostId':host,'agentId':agent,'runtimeMode':'room-conversation','nativeServer':{'manifest':'fixture-only'},'hollywoodUrl':'http://127.0.0.1:1','token':'not-a-credential'}
 wire=base64.b64encode(json.dumps(c).encode()).decode();enrolled={'authorityId':authority,'hostId':host,'agentId':agent,'machineIdentity':image.machine_identity()}
 plan={'oldBinary':'/same/native','newBinary':'/same/native','retainedNative':{'fixture':True},'transportAdoption':{'historicalUnknown':None},'targets':[{'before':wire,'after':wire}],'scope':[authority,host,agent],'priorEnrollment':enrolled}
 pin=n.prepare(plan);assert pin and pin['kind']=='native-client-sdk';plan['nativeClientBoundary']=pin
 with patch.object(image,'_json',side_effect=AssertionError('Native client must not require legacy/node files')):control=n.load(-1,c,plan)
 calls=[]
 def synthetic(url,token,method,path):
  calls.append((method,path));return {'id':agent,'authority':authority,'kind':'agent','active':True,'home_node':host}
 with patch.object(n,'request',side_effect=synthetic):n.canonical(c,control,host,agent)
 assert calls==[('GET','principals/'+agent)]
 for changed in [{**plan,'newBinary':'/other/native'},{**plan,'transportAdoption':{'historicalUnknown':{'state':'unknown'}}},{**plan,'targets':[{'before':wire,'after':base64.b64encode(json.dumps({**c,'token':'changed'}).encode()).decode()}]}]:
  assert n.prepare(changed)is None
  try:n.load(-1,c,changed)
  except ValueError:pass
  else:raise AssertionError('Changed non-SDK boundary accepted')
 try:n.load(-1,c,{**plan,'priorEnrollment':{**enrolled,'hostId':str(uuid4())}})
 except ValueError:pass
 else:raise AssertionError('Another enrolled host accepted')
 with patch.object(image,'_json',return_value={'original':'controller'})as reader:
  assert n.load(7,c,{})=={'original':'controller'};reader.assert_called_once_with(7,'controller.json')
 print(json.dumps({'passed':True,'managedEnrollmentAndDependencyPins':True,'changedCredentialsAndImageRejected':True,'legacyPathPreserved':True,'canonicalHTTPRequestSynthetic':True,'nativePathDoesNotReadLegacyOrOptionalNodeRecords':True,'nativeModels':0,'productionChanged':False}))
if __name__=='__main__':main()
