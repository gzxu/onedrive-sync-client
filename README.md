[![Build Status](https://travis-ci.com/gzxu/onedrive-sync-client.svg?branch=master)](https://travis-ci.com/gzxu/onedrive-sync-client)
[![](https://img.shields.io/pypi/v/onedrive-sync-client.svg)](https://pypi.org/project/onedrive-sync-client/)

# Two-way OneDrive Synchronization Client

*DISCLAIMER: This utility is in its early stage. Although it is designed to fail as soon as possible when conflicts are detected in order to avoid data loss, it is not guaranteed that your data is absolutely safe. Run it in a testing environment before you know what is going on*

Based on [Microsoft Graph](https://developer.microsoft.com/en-us/graph), written in Python, this utility will detect changes you made locally and changes happened in the cloud, and try to merge them on both sides. If it fails due to conflicts, for example, you renamed a file locally but assigned the same file with another filename on your phone, this utility will complain and fail before making any operations, ensuring your data to remain intact.

To try it out, simply type this into your terminal (supposing you are using GNU/Linux and `~/.local/bin` is in your `$PATH`)

```
pip install --user onedrive-sync-client # Install
# If you want to use the latest snapshot use the following line instead
# pip install --user https://github.com/gzxu/onedrive-sync-client/archive/master.zip
onedrive --set-location ~/OneDrive      # Config
onedrive                                # Sync!
```

Currently this utility utilizes [extended attributes](http://man7.org/linux/man-pages/man7/xattr.7.html) to save file identifiers locally, and modern filesystems and distributions should have this feature enabled by default. An SQLite database will be created and used as a central place to save essential information from the first time you run it, like your [login token](https://developer.microsoft.com/en-us/graph/docs/concepts/auth_overview) or the state of the whole filesystem tree at the last synchronization. We will ask you for the permissions to access your OneDrive files (of course), and to "access your information at any time", which means you do not need to login and authorize every time you use it.

## Algorithm

An essential background is that OneDrive, like almost every cloud storage providers, assigns an globally-unique identifier to every file or directory (folder), because this identifier is also linked to other metadata like whether this file is allowed to be viewed by anonymous visitors, and the list of metadata is subject to grow at any time. This effectively reduces the complexity of our algorithm.

Firstly, the filesystem tree hierarchy will be constructed on both sides. OneDrive provided us with [a simple API](https://developer.microsoft.com/en-us/graph/docs/api-reference/v1.0/api/driveitem_delta) to dump the whole tree on the cloud, recursively, with the identifier and name of each item, and additionally the checksum of each file (_Current implementation is different_). The locally tree is easily constructed with aforementioned information, and the identifier information can be read from the extended attributes of each file or directory. You can inspect the locally stored identifier to `FILENAME` by `getfattr -n user.onedrive.id FILENAME`. Originally extended attributes are used because it moves with the corresponding file, but the default file manager, Nautilus, copies all extended attributes when copying files. This results in duplicated identifiers. Also, there will be no identifiers for new locally created files, so the locally constructed tree needs to assign a temporary identifier to each file, and maintain a mapping between the real identifiers and temporary identifiers. At the same time, the saved state of the tree at the last synchronization is also loaded.

Then there are three trees, the cloud tree, the local tree and the saved tree. We need to merge them in a two-way manner. The cloud tree is then compared with the saved tree. Although we call them "trees", they are actually lists of nodes sorted by their identifiers. Each node stores its name, checksum if applies, and the identifier of its parent. For each identifier, if the corresponding nodes are the same in the cloud tree and in the saved tree, it is considered as unchanged. Even if its parent is renamed or moved, as long as the identifier of its parent remain unchanged, this node will move along with its parent. If an identifier only exists in the cloud tree, it must be newly created; if it only exists in the base tree, it must be removed in the cloud since the last synchronization. If the identifier of its parent is different, it must be moved. If its name or checksum is changed, it must be renamed or overridden. Thence, we get a change set between the cloud tree and the saved tree. Similar approaches made for the local tree, but as there would be duplicated identifiers, for every duplication, the most similar one among them will be kept, and other ones will be treated as newly created. This is not optimal, because if we copied a folder locally, there will lots of upload traffic as we need to upload the whole folder.

Now we have two change sets, one is between the cloud tree and the saved tree, and the other is between the local tree and the saved tree. Each change set consists of several operations, and each operation is in one of the types listed below:

* Create a file with a given name and a given checksum to a given directory
* Delete a given file
* Override the content of a given file with given checksum
* Rename a given file with a given name and/or move it to a given parent directory
* Create a directory with a given name to a given directory
* Delete a given directory (This directory must be empty)
* Rename a given directory with a given name and/or move it (along with all its children) to another given parent directory
* Copy a file or directory (Currently unimplemented and omitted)

This set generated from the previous step is unordered, but they must be applied in an order. Some permutations of these steps are acceptable, but other ones causes conflicts. For example, you cannot create a file before the creation of its parent. Operations may conflict with operations in the same set, which represents the actual possible order of changes from the saved tree to the new trees; they may also conflict with operations in the other set, which may render the merging process unattainable.

### Conflict checking and script sorting

There are two kinds of conflicts. One of them is conflicts between the two sets, that is, the same node cannot be both modified by the two sets. Another one is, actually more than conflicts, is sorting inside one change set and let it to be ordered. The order does not need to be considered between the two sets, because the cloud set must be applied after the local one, and actually it has been applied before the local one.

For each identifier, the corresponding node cannot be applied with conflicting operations. Conflicting operations may not happen inside one change set but only happen between the two sets, because they are generated from the same trees. Two operations with exactly the same parameters do not conflict, but if not, they conflict with each other if they have the same type of operation. Additionally, removing a node conflict with any other operation on that node. Adding node does not need to be considered here, because there will be no other operations on the same identifier.

The sorting problem is a topological sorting problem. Every operation is modeled as a vertex, and if an operation should happen after another one, there will be an oriented edge between them. Loops in this graph indicate conflict.

In order to find conflicts between different identifiers, the prerequisites and effects of each operation are marked and indexed. There are two types of prerequisites, and two corresponding types of effects: the given directory to exist and the given name inside the given directory is not occupied. An operation should be applied after these operations providing the corresponding effects to its prerequisites.

1. Create file
   * Prerequisite: The destination must exist
   * Prerequisite: The name in the destination must be available
1. Delete file
   * Effect: Release that name
1. Override file
   * No prerequisites nor effects
1. Rename and move file
   * Prerequisite: The destination must exist
   * Prerequisite: The name in the destination must be available
   * Effect: Release the original name
1. Create directory
   * Prerequisite: The destination must exist
   * Prerequisite: The name in the destination must be available
   * Effect: This directory begins to exist
1. Delete directory
   * Prerequisite: All current names must be released
   * Effect: Release that name
1. Rename and move directory
   * Prerequisite: The destination must exist
   * Prerequisite: The name in the destination must be available
   * Effect: Release the original name
   
Actually there are cases that is not covered by this algorithm, for example, creating two files with different identifiers (of course) but under the same directory with the same name is not detected. Such conflicts happen between the two change sets, and is only relevant to name conflicts. There should be more unrevealed conflicts, and thence the generated script should be tested before applied.

### Script checking and optimization

After topological sorting, the generated script is applied to a testing copy of the two trees, and if there is an operation to remove a directory, any operations to remove items from that directory can be marked as omitted, as an optimization.

## Applying Script and Saving Trees

The REST API is described on the [Microsoft Graph documentation site](https://developer.microsoft.com/en-us/graph/docs/api-reference/v1.0/resources/onedrive), and there are some points to be specifically noticed. The tree is saved to the database as tables of identifiers and properties.

### Delta listing

OneDrive provides an API to [dump the whole tree](https://developer.microsoft.com/en-us/graph/docs/api-reference/v1.0/api/driveitem_delta). This tree may be huge and the transfer process may be slow. To address this problem, the result of the last dump query can be saved, and use the delta API to generate the real cloud tree. When the delta API is not available, the fallback method can be used instead.

### Batch requests

A request agent can be used to temporarily store requests and use the [batch API](https://developer.microsoft.com/en-us/graph/docs/concepts/json_batching) to save traffic, before any force flushing. Also, some HTTP library supports HTTP 2.0 to additionally save traffic. However, this involves a more complex algorithm.

### File downloading and uploading

As OneDrive supports partial downloading, a download manager is needed especially when the file is large. There are two upload APIs, and an upload manager is also needed. The [`/content` API](https://developer.microsoft.com/en-us/graph/docs/api-reference/v1.0/api/driveitem_put_content) is easier to be used, and is suitable for files less than 4 MiB under good network condition. When the file is too large or when the network condition is bad, the [`/createUploadSession` API](https://developer.microsoft.com/en-us/graph/docs/api-reference/v1.0/api/driveitem_createuploadsession) have to be used. To upload file via this API, the parent identifier and the file name must be provided, and create an upload session with only the file identifier is unfeasible due to a bug of the server.

## Known issues

1. Some applications, namely [Gedit](https://wiki.gnome.org/Apps/Gedit), will erase the saved attributes attached to the file, because it virtually creates a new file and removed the old one. As the id information is lost, we have to do the same thing (remove and re-upload) when synchronizing
2. The delta feature is temporarily disabled due to an unresolved bug in this utility

## Future works

- [ ] Solve the aforementioned issue by detecting missing identifiers and prompting the user
- [x] Solve the aforementioned bug and revise the algorithm to cover the aforementioned situation
- [x] Optimize deletion in the cloud by pruning
- [ ] Transactional syncing to avoid unpredictable exceptions
- [ ] Optimize by omitting changes that is the same in the two change sets
- [x] Add option to force override local tree with the cloud one or vice versa
- [x] Use [`st_mtime_ns`](http://man7.org/linux/man-pages/man7/inode.7.html) to detect changes instead of checksums for faster local tree constructing and [OneDrive for Business and SharePoint Server 2016](https://developer.microsoft.com/en-us/graph/docs/api-reference/v1.0/resources/hashes) support. Checksums can be used as an auxiliary method to detect local changes, and `eTag`s can be used to detect changes in the cloud 
- [x] ~~Use DAO when handling databases when possible~~
- [x] Use SQLAlchemy as the ORM engine
- [ ] Enable Windows and/or macOS support (easy but probably unnecessary job)
- [ ] Come up with a better model describing this problem and revise the algorithm based on this
- [ ] Replenish the documentation in comments
- [ ] Sweep bug out by introducing unit tests
- [ ] Agent for batch requests, as mentioned above
- [x] Download and upload manager for unstable network connection
- [ ] Download and upload manager with multi-threading support
- [ ] Utilize the [copy API](https://developer.microsoft.com/en-us/graph/docs/api-reference/v1.0/api/driveitem_copy), however as this an asynchronous one, parallel programming is a necessity
- [ ] HTTP 2.0 support with libraries other than [`requests`](https://requests.readthedocs.io/)
- [ ] Revise the commandline user interface by list out necessary information in a human-readable manner
- [ ] Properly handle every possible exceptions
- [ ] Introduce a logging framework
- [ ] GUI with neat design
- [ ] Port to C++ when possible

## License

This project is licensed under the [GNU Affero General Public License](./LICENSE.md).
