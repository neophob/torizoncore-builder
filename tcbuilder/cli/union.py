"""Union sub-command CLI handling

The union sub-command merges a given OSTree reference (e.g. branch or commit
hash) with local changes (e.g. copied from an adjusted module using the isolate
sub-command).
"""

import os
import logging
import traceback
from tcbuilder.backend import union
from tcbuilder.errors import TorizonCoreBuilderError

def union_subcommand(args):
    """Run \"union\" subcommand"""
    log = logging.getLogger("torizon." + __name__)
    storage_dir = os.path.abspath(args.storage_directory)
    if args.diff_dir is None:
        ans = input("is this change for splash image? [y/N] ")
        if ans.lower() == "y":
            diff_dir = "/storage/splash"
        else:
            diff_dir = "/storage/changes"
    else:
        diff_dir = os.path.abspath(args.diff_dir)

    union_branch = args.union_branch

    src_ostree_archive_dir = os.path.join(storage_dir, "ostree-archive")

    if not os.path.exists(diff_dir):
        log.error(f"{diff_dir} does not exist")
        return

    if not os.path.exists(storage_dir):
        log.error(f"{storage_dir} does not exist")
        return

    try:
        commit = union.union_changes(diff_dir, src_ostree_archive_dir, union_branch)
        log.info(f"Commit {commit} has been generated for changes and ready to be deployed.")
    except TorizonCoreBuilderError as ex:
        log.error(ex.msg)  # msg from all kinds of Exceptions
        if ex.det is not None:
            log.info(ex.det)  # more elaborative message
        log.debug(traceback.format_exc())  # full traceback to be shown for debugging only

def init_parser(subparsers):
    """Initialize argument parser"""
    subparser = subparsers.add_parser("union", help="""\
    Create a commit out of isolated changes for unpacked Tezi Image""")
    subparser.add_argument("--diff-directory", dest="diff_dir",
                           help="""Path to the directory containing user changes
                           (must be same as provided for isolate).
                           Must be a file system capable of carrying Linux file system
                           metadata (Unix file permissions and xattr).""",
                           default="/storage/changes")
    subparser.add_argument("--union-branch", dest="union_branch",
                           help="""Name of branch containing the changes committed to
                           the unpacked repo.
                           """,
                           required=True)

    subparser.set_defaults(func=union_subcommand)
