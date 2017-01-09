# git-lfs-swift-server

## Description
A Git LFS server using an OpenStack Swift cluster as backend storage. Implemented in python with flask.

[Git LFS](https://github.com/git-lfs/git-lfs) is a git command line extension for managing large files.
It uses a Git LFS server for retrieving URLs, which are then used for uploading/downloading the large files.
git-lfs-swift-server is an implementation of a Git LFS server, 
which uses a configurable [OpenStack Swift](https://github.com/openstack/swift)
cluster to store the data. This server implements the
[batch API](https://github.com/git-lfs/git-lfs/blob/master/docs/api/batch.md). As web server framework, 
[Flask](http://flask.pocoo.org/) is used.

## Installation

    git clone https://github.com/cbartz/git-lfs-swift-server
    cd git-lfs-swift-server
    python setup.py install

## Configuration
In a python file:

    AUTH_URL = "https://example.com/auth/v1.0"
    TOKEN_EXPIRY = 3600
    LOGFILE = /tmp/logfile
    LOGLEVEL = INFO
    AUTH_KWARGS = {} 

Ensure to set the environment variable *GIT_LFS_SWIFT_SETTINGS_FILE=/path/to/file.py*, so that 
flask knows where to retrieve the config.

You can also set directly the settings as environment variables:

     export GIT_LFS_SWIFT_AUTH_URL="https://example.com/auth/v1.0"
     export GIT_LFS_SWIFT_TOKEN_EXPIRY=3600
     export GIT_LFS_SWIFT_LOGFILE=/tmp/logfile
     export GIT_LFS_SWIFT_LOGLEVEL=INFO


## Deployment
For testing purposes, flask ships a web server. You can just call:

     GIT_LFS_SWIFT_SETTINGS_FILE=/path/to/file.py python -m git_lfs_swift_server.server

For production, use the webserver of your choice. 
See the [Flask documentation](http://flask.pocoo.org/docs/latest/deploying/)
for more information.

## Transfer types
The git-lfs-swift server supports the required [basic](https://github.com/git-lfs/git-lfs/blob/master/docs/api/basic-transfers.md)
transfer mode. But there is an issue with that: Swift clusters have a maximum object
size (defaults to 5 GiB). Files larger then this size have to be splitted up into multiple segments. The basic
transfer mode does not support this mechanism. Therefore, the server supports the 
[custom transfer mode](https://github.com/git-lfs/git-lfs/blob/master/docs/custom-transfers.md) *swift* , too.


## Keystone
The server has been only tested with auth version 1.0 . It is possible to add additional kwargs to the
auth call, if you specify a dict *AUTH_KWARGS* in the config file. Therefore in theory, it should be possible to
use keystone, too.