import logging

from pip._internal.exceptions import InvalidWheelFilename
from pip._internal.download import unpack_url, PipSession
from pip._internal.utils.urls import path_to_url
from pip._internal.index import PackageFinder
from pip._internal.collector import LinkCollector
from pip._internal.models.link import Link
from pip._internal.models.search_scope import SearchScope
from pip._internal.models.selection_prefs import SelectionPreferences
from pip._internal.operations.prepare import make_distribution_for_install_requirement, RequirementPreparer
from pip._internal.req import (
    parse_requirements,
    InstallRequirement,
    RequirementSet,
)
from pip._internal.req.constructors import install_req_from_req_string
from pip._internal.req.req_tracker import RequirementTracker
from pip._internal.legacy_resolve import Resolver
from pip._internal.wheel import Wheel, WheelBuilder
from pip._internal.cache import WheelCache
from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.utils import canonicalize_name


LOG = logging.getLogger("pip")


def create_requirement_from_string(string, comes_from=None):
    return InstallRequirement(Requirement(string), comes_from)
