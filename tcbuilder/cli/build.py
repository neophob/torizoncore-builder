"""
CLI handling for build subcommand
"""

import logging
import os
from datetime import datetime

# import dockerbundle

from tcbuilder.errors import (FileContentMissing,
                              FeatureNotImplementedError, InvalidDataError,
                              InvalidStateError)

from tcbuilder.backend import build as bb
from tcbuilder.backend import combine as comb_be
from tcbuilder.backend import dt as dt_be
from tcbuilder.cli import deploy as deploy_cli
from tcbuilder.cli import dt as dt_cli
from tcbuilder.cli import dto as dto_cli
from tcbuilder.cli import kernel as kernel_cli
from tcbuilder.cli import images as images_cli
from tcbuilder.cli import splash as splash_cli
from tcbuilder.cli import union as union_cli

DEFAULT_BUILD_FILE = "tcbuild.yaml"

log = logging.getLogger("torizon." + __name__)


def create_template(config_fname):
    """Main handler for the create-template mode of the build subcommand"""

    print(f"Generating '{config_fname}' (not yet implemented)")


def handle_input_section(props, **kwargs):
    """Handle the input section of the configuration file

    :param props: Dictionary holding the data of the section.
    :param kwargs: Keyword arguments that are forwarded to the handling
                   functions of the subsections.
    """

    if "easy-installer" in props:
        handle_easy_installer_input(props["easy-installer"], **kwargs)
    elif "ostree" in props:
        handle_ostree_input(props["ostree"], **kwargs)
    else:
        raise FileContentMissing(
            "No kind of input specified in configuration file")


def handle_easy_installer_input(props, storage_dir=None, download_dir=None):
    """Handle the input/easy-installer subsection of the configuration file

    :param props: Dictionary holding the data of the subsection.
    :param storage_dir: Absolute path of storage directory. This is a required
                        keyword argument.
    :param download_dir: Directory where files should be downloaded to or
                         obtained from if they already exist (TODO).
    """

    log.debug(f"Handling easy-installer section: {str(props)}")

    assert storage_dir is not None, "Parameter `storage_dir` must be passed"

    if "local" in props:
        images_cli.images_unpack(
            props["local"], storage_dir, remove_storage=True)

    elif ("remote" in props) or ("toradex-feed" in props):
        if "toradex-feed" in props:
            # Evaluate if it makes sense to supply a checksum here too (TODO).
            remote_url, remote_fname = bb.make_feed_url(props["toradex-feed"])
            cksum = None
        else:
            # Parse remote which may contain integrity checking information.
            remote_url, remote_fname, cksum = bb.parse_remote(props["remote"])
            log.debug(f"Remote URL: {remote_url}, name: {remote_fname}, "
                      f"expected sha256: {cksum}")

        # Next call will download the file if necessary (TODO).
        local_file, is_temp = \
            bb.fetch_remote(remote_url, remote_fname, cksum, download_dir)

        try:
            images_cli.images_unpack(local_file, storage_dir, remove_storage=True)
        finally:
            # Avoid leaving files in the temporary directory (if it was used).
            if is_temp:
                os.unlink(local_file)

    else:
        raise FileContentMissing(
            "No known input type specified in configuration file")


def handle_ostree_input(props, **kwargs):
    """Handle the input/easy-installer subsection of the configuration file"""
    raise FeatureNotImplementedError(
        "Processing of ostree archive inputs is not implemented yet.")


def handle_customization_section(props, storage_dir=None):
    """Handle the customization section of the configuration file

    :param props: Dictionary holding the data of the section.
    :param storage_dir: Absolute path of storage directory. This is a required
                        keyword argument.
    """

    assert storage_dir is not None, "Parameter `storage_dir` must be passed"

    log.debug(f"Handling customization section: {str(props)}")

    if "splash-screen" in props:
        splash_cli.splash(props["splash-screen"], storage_dir=storage_dir)

    if "device-tree" in props:
        handle_dt_customization(props["device-tree"], storage_dir=storage_dir)

    if "kernel" in props:
        handle_kernel_customization(props["kernel"], storage_dir=storage_dir)

    # Filesystem changes are actually handled as part of the output processing.
    fs_changes = props.get("filesystem")

    return fs_changes


def handle_dt_customization(props, storage_dir=None):
    """Handle the device-tree customization section."""

    log.debug(f"Handling DT subsection: {str(props)}")

    if "custom" in props:
        dt_cli.dt_apply(dts_path=props["custom"],
                        storage_dir=storage_dir,
                        include_dirs=props.get("include-dirs", []))

    overlay_props = props.get("overlays", {})
    if overlay_props.get("clear", True):
        dto_cli.dto_remove_all(storage_dir)

        if "remove" in overlay_props:
            log.info("Individual overlay removal ignored because they've all been "
                     "removed due to the 'clear' property")

    elif "remove" in overlay_props:
        for overl in overlay_props["remove"]:
            dto_cli.dto_remove_single(overl, storage_dir, presence_required=False)

    if "add" in overlay_props:
        # We enable the overlay apply test only if it is possible to do it.
        test_apply = bool(dt_be.get_current_dtb_basename(storage_dir))
        log.debug(f"Overlay apply test is {['disabled','enabled'][test_apply]}")
        for overl in overlay_props["add"]:
            dto_cli.dto_apply(
                dtos_path=overl,
                dtb_path=None,
                include_dirs=props.get("include-dirs", []),
                storage_dir=storage_dir,
                allow_reapply=False,
                test_apply=test_apply)


def handle_kernel_customization(props, storage_dir=None):
    """Handle the kernel customization section."""

    if "modules" in props:
        for mod_props in props["modules"]:
            mod_source = mod_props["source-dir"]
            log.info(f"Build module from {mod_source}...")
            kernel_cli.kernel_build_module(
                source_dir=mod_source,
                storage_dir=storage_dir,
                autoload=mod_props.get("source-dir", False))

    if "arguments" in props:
        log.info("Setting kernel arguments...")
        kernel_cli.kernel_set_custom_args(
            kernel_args=props["arguments"],
            storage_dir=storage_dir)


def handle_output_section(props, storage_dir, extra_changes_dirs=None):
    """Handle the output section of the configuration file

    :param props: Dictionary holding the data of the section.
    :param storage_dir: Absolute path of storage directory. This is a required
                        keyword argument.
    """

    # ostree data is currently optional.
    ostree_props = props.get("ostree", {})

    # Parameters to pass to union()
    union_params = {
        "changes_dirs": None,
        "storage_dir": storage_dir,
        "extra_changes_dirs": extra_changes_dirs
    }

    if "branch" in ostree_props:
        union_params["union_branch"] = ostree_props["branch"]
    else:
        # Create a default branch name based on date/time.
        nowstr = datetime.now().strftime("%Y%m%d%H%M%S")
        union_params["union_branch"] = f"tcbuilder-{nowstr}"

    if "commit-subject" in ostree_props:
        union_params["commit_subject"] = ostree_props["commit-subject"]
    if "commit-body" in ostree_props:
        union_params["commit_body"] = ostree_props["commit-body"]

    union_cli.union(**union_params)

    # Handle the "output.ostree.local" property (TODO).
    # Handle the "output.ostree.remote" property (TODO).

    tezi_props = props.get("easy-installer", {})

    # Note that the following test should never fail (due to schema validation).
    assert "local" in tezi_props, "'local' property is required"

    output_dir = tezi_props["local"]
    if os.path.isabs(output_dir):
        raise InvalidDataError(
            f"Image output directory '{output_dir}' is not relative")
    output_dir = os.path.abspath(output_dir)

    deploy_cli.deploy_tezi_image(
        ostree_ref=union_params["union_branch"],
        output_dir=output_dir,
        storage_dir=storage_dir, deploy_sysroot_dir=deploy_cli.DEFAULT_DEPLOY_DIR,
        image_name=tezi_props.get("name"),
        image_description=tezi_props.get("description"),
        licence_file=tezi_props.get("licence"),
        release_notes_file=tezi_props.get("release-notes"))

    bundle_props = tezi_props.get("bundle", {})

    if "dir" in bundle_props:
        # Do a combine "in place" to avoid creating another directory.
        comb_be.combine_image(
            image_dir=output_dir,
            bundle_dir=bundle_props["dir"],
            output_directory=None,
            image_name=tezi_props.get("name"),
            image_description=tezi_props.get("description"),
            licence_file=tezi_props.get("licence"),
            release_notes_file=tezi_props.get("release-notes"))

    # Implement this urgently (TODO)
    elif "compose-file" in bundle_props:
        raise FeatureNotImplementedError("compose-file property is not handled yet")

    #     #####
    #     dockerbundle.download_containers_by_compose_file(
    #         output_dir, compose_file, host_workdir,
    #         docker_username, docker_password, registry,
    #         use_host_docker, platform, output_filename)


def build(config_fname, storage_dir, substs=None, enable_subst=True):
    """Main handler for the normal operating mode of the build subcommand"""

    log.info(f"Building image as per configuration file '{config_fname}'...")
    log.debug(f"Substitutions ({['disabled', 'enabled'][enable_subst]}): "
              f"{substs}")

    config = bb.parse_config_file(config_fname)

    # ---
    # Handle each section.
    # ---

    if "input" not in config:
        # Raise a parse error instead (TODO).
        raise FileContentMissing("No input specified in configuration file")

    if "output" not in config:
        # Raise a parse error instead (TODO).
        raise FileContentMissing("No output specified in configuration file")

    # Check if output directory already exists and fail if it does.
    output_dir = config["output"]["easy-installer"]["local"]
    if os.path.exists(output_dir):
        raise InvalidStateError(
            f"Output directory {output_dir} must not exist.")

    # Input section (required):
    handle_input_section(config["input"], storage_dir=storage_dir)

    # Customization section (currently optional).
    fs_changes = handle_customization_section(
        config.get("customization", {}), storage_dir=storage_dir)

    # Output section (required):
    handle_output_section(
        config["output"],
        storage_dir=storage_dir, extra_changes_dirs=fs_changes)

    # print(config)


def do_build(args):
    """Wrapper of the build command that unpacks argparse arguments"""

    print(args)

    if args.create_template:
        # Template creating mode.
        create_template(args.config_fname)
    else:
        # Normal build mode.
        build(args.config_fname, args.storage_directory,
              substs=bb.parse_assignments(args.assignments),
              enable_subst=args.enable_substitutions)


def init_parser(subparsers):
    """Initialize "build" subcommands command line interface."""

    parser = subparsers.add_parser(
        "build",
        help=("Customize a Toradex Easy Installer image based on settings "
              "specified via a configuration file."))

    parser.add_argument(
        "-c", "--create-template", dest="create_template",
        default=False, action="store_true",
        help=("Request that a template file be generated (with the name "
              "defined by --file)."))

    parser.add_argument(
        "-f", "--file", metavar="CONFIG", dest="config_fname",
        default=DEFAULT_BUILD_FILE,
        help=("Specify location of the build configuration file "
              f"(default: {DEFAULT_BUILD_FILE})."))

    parser.add_argument(
        "-s", "--set", metavar="ASSIGNMENT", dest="assignments",
        default=[], action="append",
        help=("Assign values to variables (e.g. VER=\"1.2.3\"). This can "
              "be used multiple times."))

    parser.add_argument(
        "-n", "--no-subst", dest="enable_substitutions",
        default=True, action="store_false",
        help="Disable the variable substitution feature.")

    parser.set_defaults(func=do_build)
