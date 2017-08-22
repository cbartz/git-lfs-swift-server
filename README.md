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

    AUTH_URL = "https://example.com/auth/v1.0" # Required for token Auth
    BASE_URL = "https://example.com" # Required for tempURL Auth
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

## Usage
The swift container and account used for storing the files will be determined
by the client. GIT-LFS uses HTTP Basic authentication,
and its required to use the same username/password combination
as when authenticating against the swift cluster. It is common to use the form _user:account_
as username to authenticate against a swift cluster.
This does not work well with HTTP Basic authentication,
because the colon _:_ is already used as a delimiter. Therefore, replace _:_ by _;_ when
authenticating against a git-lfs-swift server.

The swift account is automatically retrieved by the username 
(technically: The storage url the auth middleware is returning is used),
if the account is not specified explicitly in the LFS Server URL. Specifying
the account explicitly makes sense if the user is accessing a space which
does not belong to his own 
(e.g. using the [ACL](https://docs.openstack.org/developer/swift/overview_acl.html)
mechanism).

Beyond that, it is possible to use [prefix-based temporary URLs](https://docs.openstack.org/swift/latest/api/temporary_url_middleware.html)
with an empty prefix (thus valid for a whole container).
They have the advantage that people without credentials for the swift cluster can access the 
LFS objects. In this case, no username and password is required and HTTP Basic auth
can be disabled in the LFS config file. Authentication with temporary URLs require
that the variable _BASE_URL_ is defined in the server config file.

In summary, there are three kinds of a URL:

    <host>/<container>
    <host>/<account>/<container>
    <host>/<account>/<container>/read_<readsig>/write_<writesig>/<expires_at>

Example: If all the files should end up in a container
called _mycontainer_ and the domain of the git-lfs-swift server is _example.com_ 
use following command to setup the LFS URL:

    git config lfs.url https://example.com/mycontainer

If _mycontainer_ lies within a different account, specify it before the container part:

    git config lfs.url https://example.com/AUTH_otheraccount/mycontainer

And, if a prefix-based temporary URL is used, the command could look like:

    git config lfs.url https://example.com/AUTH_account/mycontainer/read_eb1566dd06c757566a46f46134404b6a047913e1/write_45e76be84e45ed9f0c08b5ed63bde3ea64f41100/1503915711/

## Transfer types
The git-lfs-swift server supports the required [basic](https://github.com/git-lfs/git-lfs/blob/master/docs/api/basic-transfers.md)
transfer mode. But there is an issue with that: Swift clusters have a maximum object
size (defaults to 5 GiB). Files larger then this size have to be split up into multiple segments. The basic
transfer mode does not support this mechanism. Therefore, the server supports the 
[custom transfer mode](https://github.com/git-lfs/git-lfs/blob/master/docs/custom-transfers.md) called
[swift](https://github.com/cbartz/git-lfs-swift-transfer-agent), too.
This mode is currently not compatible with prefix-based temporary URL authentication.

## Keystone
The server has been only tested with auth version 1.0 . It is possible to add additional kwargs to the
auth call, if you specify a dict *AUTH_KWARGS* in the config file. Therefore in theory, it should be possible to
use keystone, too.