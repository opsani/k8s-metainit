#!/usr/bin/python3

import sys
import time
import traceback

# import requests

import json

from kubernetes import client, config

# imports for exception classes only:
import urllib3.exceptions
try:
    import http.client as httplib
except ImportError:
    import httplib

# 'compact' format json encode (no spaces)
#json_enc = json.JSONEncoder(separators=(",",":")).encode

# special label to mark 'initializer controller' pods; any pod having this label will have all its initializers cleared
# by this script.
WATCH_LABEL="k8s.opsani.io/initializer"
if len(sys.argv)>1:
    WATCH_LABEL=sys.argv[1]

# disabled, use k8s python client instead (kubernetes.client.api_client.ApiClient())
#base = "http://localhost:8080"
base = ""

api = "api/v1" # TODO: update if needed on newer k8s

# debug
def dprint(*args):
    print(*args, file=sys.stderr)
    sys.stderr.flush()

e = False
try:
    config.load_incluster_config()
    dprint("loaded in-cluster config")
except config.ConfigException:
    try:
        config.load_kube_config()
        dprint("loaded config from file")
    except (config.ConfigException, FileNotFoundError):
        dprint("empty config")
        e = True
        pass # silently try with defaults

cfg = client.Configuration()
if e: # if we got the default config, replace host (FIXME: this is to make the code work as the previous version did, when ran on a master node where the plain HTTP port is open)
    cfg.host = "http://localhost:8080"

#clt = client.rest.RESTClientObject(cfg)
#base = cfg.host
clt = client.api_client.ApiClient(cfg)
base = ""

def req(method, tgt, **args):
    try:
        h = args.pop("headers")
        args["header_params"] = h
    except KeyError:
        pass
    args["response_type"] = object # just return the data as-is
    args["auth_settings"] = ['BearerToken']
    return clt.call_api(tgt, method, **args)[0]

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
    dprint("METAINIT POD:", obj["metadata"]["name"]) # DEBUG DISABLE ME
    try:
        r = req("PATCH",tgt,
           headers={"Accept":"application/json","Content-Type":"application/json-patch+json"},
           body=patch
           )
    except client.api_client.ApiException as x:
        # available bits from the response: x.status, x.reason, x.body, x.headers
        dprint("PATCH FAILED:",x.status, x.reason, x.body, x.headers)
        pass

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
    r = req("GET", tgt, _preload_content=False)
    # except client.api_client.ApiException as x: - let it fail

    l = ""
    try:
        for chunk in r.read_chunked(decode_content=False):
            if isinstance(chunk, bytes):
                chunk = chunk.decode('utf8')

            l += chunk
            a = l.split("\n")
            if l.endswith("\n"):
                l = ""
            else:
                l = a[-1]
                a = a[:-1]

            for ln in a:
                if ln:
                    try:
                       c = json.loads(ln)
                    except Exception as x:
                        dprint("invalid watch data: ", str(x))
                        return None
                    v = w1(c)
                    if v is None: return v # go back for full rescan
    except urllib3.exceptions.ProtocolError as x:
        if len(x.args)>=2 and isinstance(x.args[1], httplib.IncompleteRead):
            return v

    # if/when server closes connection on us
    return v

def scan_all():

    qry = "pods?includeUninitialized=true"
    tgt = "/".join( (base, api, qry) )

    try:
        # TODO: use multiple requests, in case the list is long
        r = req("GET", tgt, headers={"Accept":"application/json"}, _request_timeout=10)
    except client.api_client.ApiException as x:
        # status is not 2xx
        # request failure, log error and long back-off
        dprint("API failed: {} {}".format(x.status, x.reason))
        time.sleep(20)
        return None
    except Exception as x: # TODO: limit to requests-specific exceptions
        # if conn. error: back-off delay to allow kube-apisrv to start
        time.sleep(2)
        return None

#    pods = json.loads(r.data)
    pods = r
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
