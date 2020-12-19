import logging

from pip._internal.exceptions import InvalidWheelFilename
from pip._internal.network.session import PipSession
from pip._internal.utils.urls import path_to_url
from pip._internal.index.package_finder import PackageFinder
from pip._internal.index.collector import LinkCollector
from pip._internal.models.link import Link
from pip._internal.models.search_scope import SearchScope
from pip._internal.models.selection_prefs import SelectionPreferences
from pip._internal.operations.prepare import make_distribution_for_install_requirement, RequirementPreparer
from pip._internal.network.download import Downloader
from pip._internal.req import parse_requirements, InstallRequirement
from pip._internal.req.constructors import install_req_from_req_string, install_req_from_parsed_requirement
from pip._internal.req.req_tracker import get_requirement_tracker
from pip._internal.resolution.legacy.resolver import Resolver
from pip._internal.wheel_builder import build, should_build_for_wheel_command
from pip._internal.models.wheel import Wheel
from pip._internal.cache import WheelCache
from pip._internal.utils.temp_dir import global_tempdir_manager
from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.utils import canonicalize_name


LOG = logging.getLogger("pip")


def create_requirement_from_string(string, comes_from=None):
    return InstallRequirement(Requirement(string), comes_from)
