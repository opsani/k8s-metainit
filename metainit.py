#!/usr/bin/python3

import sys
import time
import traceback

import requests

import json
# 'compact' format json encode (no spaces)
#json_enc = json.JSONEncoder(separators=(",",":")).encode

# special label to mark 'initializer controller' pods; any pod having this label will have all its initializers cleared
# by this script.
WATCH_LABEL="k8s.opsani.io/initializer"
if len(sys.argv)>1:
    WATCH_LABEL=sys.argv[1]

# TODO: chk that this is always open on all master nodes:
base = "http://localhost:8080"

api = "api/v1" # TODO: update if needed on newer k8s


# debug
def dprint(*args):
    print(*args, file=sys.stderr)
    sys.stderr.flush()

def check_and_patch(obj):
    # if no initializers, do nothing
    # dprint("POD:", repr(obj["metadata"])) # DEBUG
    if "pending" not in obj["metadata"].get("initializers",{}):
        return
    # test for special label
    if WATCH_LABEL not in obj["metadata"].get("labels"):
        return

    patch = [{"op": "remove", "path": "/metadata/initializers/pending"}]
#curl -k -v -XPATCH  -H "Accept: application/json" -H "Content-Type: application/json-patch+json" -H "User-Agent: kubectl/v1.10.3 (linux/amd64) kubernetes/2bba012" -H "Authorization: Basic YWRtaW46UVFsOTdvdjFPaTVJZkZ5TUJNNlphZm9OS3ZoSm1zWkU=" https://api-k8s-lk-k8s-local-vu4b7e-1242925830.us-east-1.elb.amazonaws.com/api/v1/namespaces/default/pods/servo-k8s-multijob-667fbd569b-c9pwl
    qry = "namespaces/{}/pods/{}".format(obj["metadata"]["namespace"], obj["metadata"]["name"]) #? or use metadata["selfLink"], not sure if available on watch
    tgt = "/".join( (base, api, qry) )
    r = requests.patch(
       tgt,
       headers={"Accept":"application/json","Content-Type":"application/json-patch+json"},
       json=patch)

    # ignore status (TODO: however, if conn error, maybe trigger full rescan, jic)

def w1(c):
    obj = c["object"]
    if c["type"] == "ERROR":
        # dprint("watch err: ", repr(c)) # DEBUG
        return None # likely 'version too old' - trigger restart
        # {"type":"ERROR","object":{"kind":"Status","apiVersion":"v1","metadata":{},"status":"Failure","message":"too old resource version: 1 (3473)","reason":"Gone","code":410}}

    v = obj["metadata"]["resourceVersion"]

    if c["type"] not in ("ADDED", "MODIFIED"):
        return v

    if obj["kind"] != "Pod":
        # warn, shouldnt happen
        return v

    check_and_patch(obj)

    return v


def watch(v):
    qry = "pods?includeUninitialized=true&watch=1&resourceVersion="+str(v)
    tgt = "/".join( (base, api, qry) )

    # dprint("\n\nWATCH:", tgt)
    r = requests.get(tgt, stream=True)
    if r.encoding is None: # ensure there's *something* set as encoding
        r.encoding = 'utf-8'

    l = ""
    for chunk in r.iter_content(decode_unicode=True):
        # accumulate a line; for some reason r.iter_lines() doesn't work well
        l += chunk
        if not chunk.endswith("\n"): continue
        try:
            c = json.loads(l)
        except Exception as x:
            dprint("invalid watch data: ", str(x))
            return None
        l = ""
        v = w1(c)
        if v is None: return v # go back for full rescan

    # if/when server closes connection on us
    return v

def scan_all():

    qry = "pods?includeUninitialized=true"
    tgt = "/".join( (base, api, qry) )

    try:
        # TODO: use multiple requests, in case the list is long
        r = requests.get(tgt, headers={"Accept":"application/json"}, timeout=10)
    except Exception as x: # TODO: limit to requests-specific exceptions
        # if conn. error: back-off delay to allow kube-apisrv to start
        time.sleep(2)
        return None

    if not r.ok: # request failure, log error and long back-off
        #
        dprint("API failed: {} {}".format(r.status_code, r.reason))
        time.sleep(20)
        return None

    pods = r.json()
    # dprint("\n\nEXISTING:")
    for obj in pods.get("items", []):
        check_and_patch(obj)

    v = pods["metadata"]["resourceVersion"]
    return v

def loop():
    """main loop - scan all pods, then sit on a watch. If the watch ends
    with an error, re-do full scan, otherwise re-start the watch from the
    current version"""

    v = None
    while True:
        try:
            if v is None:
                v = scan_all()
            if v is None:
                continue # re-do scan, if it failed
            v = watch(v)
        except Exception as x:
            v = None # rescan, just in case
            traceback.print_exc()

if __name__ == "__main__":
    loop()
