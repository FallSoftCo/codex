"""Settle one old local journal from accepted canonical pre-dispatch recovery.

Metadata only: never starts a native process, sends input or modifies the
canonical request. Preserve the original local observation before closing its
old attempt index, so normal new-generation claim admission can proceed.
"""
import json
import os
from .journal import saved
from .collaboration_bridge import require


def settle(journal, record, captured, config):
    proof=captured.get('preNativeRecovery')
    if proof is None:return None
    d=captured['delivery'];old=record['delivery']
    require(proof.get('schema')=='hollywood-accepted-pre-native-recovery/v1'
        and proof.get('outcome')=='native_launch_not_dispatched'
        and proof.get('originalAttemptPreserved') is True
        and proof.get('nativeReplayAdmitted') is False
        and (proof['authorityId'],proof['deliveryId'],proof['agentId'],proof['hostId'],
             proof['sourceRequestId'],proof['previousGeneration'],proof['previousClaimId'])
        ==(old['authority'],old['id'],config['agentId'],config['hostId'],
           record['request']['id'],old['generation'],old['claim_id'])
        and d['id']==old['id'] and d['event']==record['request']['id']
        and d['agent']==config['agentId'] and d['host']==config['hostId']
        and d['generation']==old['generation'] and d['claim_id'] is None
        and d['state']=='pending' and not d['cancellation_requested']
        and d['native_thread'] is None and d['native_turn'] is None
        and not record.get('nativeThread') and not record.get('nativeTurn'),
        'Accepted pre-native recovery does not match the exact original local attempt')
    require(all(not (journal.directory/name).exists() for name in
        ('guardian-registration-attestation.json','native-process.json',
         'native-attachment-intent.json','native-admission-attestation.json')),
        'Local launch/admission evidence requires separate reconciliation')
    original=journal.directory/'execution.before-pre-native-recovery.json'
    settled={**record,'state':'failed','modelsStarted':0,'preNativeRecovery':proof,'reconciled':True}
    if original.exists():
        before=json.loads(original.read_text())
        require(before==record or {**before,'state':'failed','modelsStarted':0,
                'preNativeRecovery':proof,'reconciled':True}==record,
                'Original prelaunch observation differs')
    else:saved(original,record)
    saved(journal,settled)
    retired=retire_claim(journal,old['claim_id'])
    return {'state':'failed','originalRequestState':'pending','nativeReplay':False,
            'modelsStarted':0,'source':'Accepted canonical pre-native recovery',
            'originalLocalObservationPreserved':True,'residentClaimRetired':retired}


def retire_claim(journal, claim_id):
    path=journal.store.state/'resident-claim.json'
    if not path.exists():return False
    intent=json.loads(path.read_text())
    if intent.get('operationId')!=claim_id:return False
    original=journal.directory/'resident-claim.before-pre-native-recovery.json'
    if original.exists():
        require(json.loads(original.read_text())==intent,'Original resident claim differs')
    else:saved(original,intent)
    require(json.loads(path.read_text())==intent,'Resident claim changed during settlement')
    path.unlink()
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
    return True
