# k8s-metainit
Universal Initializer Controller for Initializer Controllers

**metainit** can be installed as a static pod on Kubernetes clusters to watch for and initialize any pods that have a special label. The "initialization" done by **metainit** is a no-op, it simply removes all pending initializers from the pod's metadata. This allows avoiding the deadlock that is normally created when there is an initializer configuration present, but the pod that is meant to recognize this configuration and act on it is either not yet created or has been temporarily removed for upgrade and re-start.

## Building and Installing Metainit

Build the metainit container image and tag it as desired, so that it can be stored in a Docker registry that is accessible to your cluster nodes:

    docker build -t my_registry/k8s-metainit:latest .
    docker push my_registry/k8s-metainit:latest

Make a copy of the `pod-metainit.manifest` file and edit it as follows:

- change the line starting with `image:` to match the new **metainit** image that you built (e.g., `my_registry/k8s-metainit:latest`). 
- (optional) change the last item in the line starting with `command:` to a unique label name that you want to use as a special marker on pods that are to be auto-initialized by **metainit**. The default `k8s.opsani.io/initializer` can be safely used, as well. **IMPORTANT**: if changing this, choose a label that is unique and will never be used for anything else except to add to the metadata of "initializer controller" pods.

Find where the kubelet manifests directory is on the cluster's master nodes. This varies depending on the method used to set up the cluster. On one of the master nodes, run:

    ps -C kubelet -Fww

and find the text following the `--pod-manifest-path` option on the `kubelet` command line.

Copy your customized version of the `pod-metainit.manifest` file into the pod manifest directory on each of the master nodes. This will start **metainit** immediately and keep it running at all times on the master nodes.

NOTE: if the cluster has an external mechanism for creating and updating master nodes (e.g., for automatic scaling or for spawning new VMs configured as k8s master ndes in case a node is lost), the configuration of that mechanism needs to be modified so that it always adds the pod-metainit.manifest file to new master nodes.

## Configuring Initialization Controllers

To make use of the automatic clearing of all pending initializers provided by **metainit**,
a label needs to be added to the pod metadata.
Note: if using a higher-level control object such as a Kubernetes
Deployment, the label should be added to the pod template (not the control object metadata!).
The label key should match the string given as argument to **metainit**
(as set in the `command` string in the **metainit** pod manifest).
Only the label key is important, the value is ignored.
 
Example (snippet from a Deployment spec):                                                            *

    spec:
      replicas: 1
      template:
        metadata:
          name: servo-k8s-multijob
          labels:
            app: servo-k8s-multijob
            "k8s.opsani.io/initializer": ""

