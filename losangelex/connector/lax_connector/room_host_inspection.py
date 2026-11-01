"""Read an original factory installation using a separately reviewed runtime.

No installer dispatch, spec rewrite or service start is permitted here. The
current administrator's accepted release must own the actual maintenance code;
the worker's original interpreter/configuration/receipts remain historical.
"""
import hashlib
import json
import os
import sys
from pathlib import Path
from uuid import UUID


def inspect_original(file, owner, expected_sha256):
    if os.geteuid() != 0:
        raise PermissionError('Verified maintenance inspection administrator required')
    file = Path(file)
    raw = file.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('Original factory specification CAS differs')
    spec = json.loads(raw)
    authority, host, owner = [str(UUID(v)) for v in (spec['authorityId'], spec['hostId'], owner)]
    if str(UUID(spec['agentId'])) == owner:
        raise ValueError('Factory inspection cannot replace its owning administrator')
    from . import native_image_upgrade as image, native_release as release
    from . import service_observer as observer
    from .linux_worker import inspect_completed
    # Snapshot the owner, inspect the worker, then validate the owner again.
    # Never nest registries; release writers remain exclusively serialized.
    with image.registry_read_lock(observer.directory(authority, host, owner)) as fd:
        image.require_settled_transition(fd)
        accepted = image._json(fd, release.CURRENT)
        runtime, _, _ = release.runtime_spec(authority, owner)
        root = Path(accepted['closure']['root'])
        module = Path(__file__).resolve(strict=True)
        if (accepted['scope'] != [authority, host, owner]
                or runtime['hostId'] != host
                or runtime['interpreter'] != sys.executable
                or accepted['newInterpreter'] != sys.executable
                or not Path(sys.executable).is_relative_to(root)
                or not module.is_relative_to(root)
                or module.relative_to(root).as_posix() not in accepted['closure']['identities']):
            raise PermissionError('Maintenance interpreter/code is not the owning accepted release')
        pin = {'schema': 'lax-factory-inspection-runtime/v1',
               'authorityId': authority, 'hostId': host, 'ownerAgentId': owner,
               'interpreter': sys.executable, 'originalSpecSha256': expected_sha256,
               'acceptedReleaseOperation': accepted['operationId'],
               'acceptedReleaseDigest': observer.digest(accepted)}
    result = inspect_completed(spec)
    if file.read_bytes() != raw:
        raise ValueError('Original factory specification changed during inspection')
    with image.registry_read_lock(observer.directory(authority, host, owner)) as fd:
        image.require_settled_transition(fd)
        if image._json(fd, release.CURRENT) != accepted:
            raise ValueError('Owning maintenance release changed during inspection')
    return {**result, 'maintenanceRuntime': pin}
