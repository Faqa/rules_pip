import contextlib
import functools
import logging
import os
import shutil
import tempfile

from piprules import pipcompat, urlcompat, util


LOG = logging.getLogger(__name__)


class Error(Exception):

    """Base exception for the resolve module"""


def resolve_requirement_set(requirement_set, pip_session, index_urls, wheel_dir):
    LOG.info("Resolving dependencies and building wheels")

    resolver_factory = ResolverFactory(pip_session, index_urls, wheel_dir)

    with pipcompat.global_tempdir_manager():
        with resolver_factory.make_resolver() as resolver:
            return resolver.resolve(requirement_set)


class ResolverFactory(object):

    def __init__(self, pip_session, index_urls, wheel_dir):
        self.pip_session = pip_session
        self.index_urls = index_urls
        self.wheel_dir = wheel_dir

    @contextlib.contextmanager
    def make_resolver(self):
        with pipcompat.get_requirement_tracker() as requirement_tracker:
            with _WorkDirs(tempfile.mkdtemp()) as work_dirs:
                finder = self._make_finder()
                preparer = self._make_preparer(requirement_tracker, work_dirs, finder)
                pip_resolver = self._make_pip_resolver(finder, preparer)

                yield Resolver(
                    self.pip_session,
                    pip_resolver,
                    work_dirs,
                    self.wheel_dir,
                )

    def _make_finder(self):
        return pipcompat.PackageFinder.create(
            link_collector=pipcompat.LinkCollector(
                session=self.pip_session,
                search_scope=pipcompat.SearchScope.create(
                    find_links=[],
                    index_urls=self.index_urls,
                ),
            ),
            selection_prefs=pipcompat.SelectionPreferences(
                allow_yanked=False,
                prefer_binary=True,
            ),
        )

    def _make_preparer(self, requirement_tracker, work_dirs, finder):
        return pipcompat.RequirementPreparer(
            build_dir=work_dirs.build,
            download_dir=None,
            src_dir=work_dirs.src,
            wheel_download_dir=work_dirs.wheel,
            build_isolation=True,
            req_tracker=requirement_tracker,
            downloader=pipcompat.Downloader(
                self.pip_session,
                progress_bar="off",
            ),
            finder=finder,
            require_hashes=False,
            use_user_site=False,
        )

    def _make_pip_resolver(self, finder, preparer):
        return pipcompat.Resolver(
            preparer=preparer,
            finder=finder,
            make_install_req = functools.partial(
                pipcompat.install_req_from_req_string,
                isolated=True,
                wheel_cache=None,
                use_pep517=None,
            ),
            use_user_site=False,
            ignore_dependencies=False,
            ignore_installed=True,
            ignore_requires_python=True,
            force_reinstall=False,
            upgrade_strategy="to-satisfy-only",
        )


class _WorkDirs(object):

    def __init__(self, base):
        self.base = base

    @property
    def build(self):
        return os.path.join(self.base, "build")

    @property
    def src(self):
        return os.path.join(self.base, "src")

    @property
    def wheel(self):
        return os.path.join(self.base, "wheel")

    def __enter__(self):
        self.create_all()
        return self

    def create_all(self):
        util.ensure_directory_exists(self.build)
        util.ensure_directory_exists(self.src)
        util.ensure_directory_exists(self.wheel)

    def __exit__(self, *args, **kwargs):
        self.delete_all()

    def delete_all(self):
        shutil.rmtree(self.base)


class Resolver(object):

    def __init__(self, session, pip_resolver, work_dirs, wheel_dir):
        self._session = session
        self._pip_resolver = pip_resolver
        self._work_dirs = work_dirs
        self._wheel_dir = wheel_dir

    def resolve(self, requirement_set):
        self._pip_resolver.resolve(requirement_set)

        requirements = requirement_set.requirements.values()

        built_wheels = self._build_wheels_if_necessary(requirements)

        return [
            self._create_resolved_requirement(requirement, False)
            for requirement in requirements if requirements not in built_wheels
        ] + [
            self._create_resolved_requirement(requirement, True)
            for requirement in built_wheels
        ]

    def _build_wheels_if_necessary(self, requirements):
        build_successes, build_failures = pipcompat.build(
            requirements=[req for req in requirements if pipcompat.should_build_for_wheel_command(req)],
            wheel_cache=pipcompat.WheelCache(None, None),
            build_options=[],
            global_options=[],
        )
        if build_failures:
            raise WheelBuildError(build_failures)
        return build_successes


    def _create_resolved_requirement(self, requirement, use_local_wheel_source):
        LOG.debug("Creating resolved requirement for %s", requirement.name)

        abstract_dist = pipcompat.make_distribution_for_install_requirement(requirement)
        dist = abstract_dist.get_pkg_resources_distribution()

        dependencies = [
            pipcompat.canonicalize_name(dep.name)
            for dep in dist.requires(requirement.extras)
        ]
        version = dist.version

        if use_local_wheel_source:
            self._set_link_to_local_wheel(requirement)

        link = requirement.link
        source = ResolvedRequirementSource(link.url_without_fragment)

        source.sha256 = (
            link.hash
            if link.hash and link.hash_name == "sha256"
            else self._compute_sha256_sum(requirement)
        )

        return ResolvedRequirement(
            pipcompat.canonicalize_name(requirement.name),
            version,
            source,
            is_direct=requirement.is_direct,
            dependencies=dependencies,
            extras=requirement.extras,
        )

    def _set_link_to_local_wheel(self, requirement):
        temp_wheel_path = requirement.local_file_path
        wheel_path = _copy_file_if_missing(temp_wheel_path, self._wheel_dir)
        url = pipcompat.path_to_url(wheel_path)

        LOG.debug("Setting source of %s to %s", requirement.name, url)
        requirement.link = pipcompat.Link(url, comes_from=wheel_path)

        # This is necessary for the make_distribution_for_install_requirement step, which relies on an
        # unpacked wheel that looks like an installed distribution
        requirement.ensure_has_source_dir(self._work_dirs.build)
        pipcompat.unpack_file_url(
            link=requirement.link,
            location=requirement.source_dir,
        )

    def _compute_sha256_sum(self, requirement):
        LOG.debug("Computing sha256 sum for %s", requirement.name)
        return util.compute_file_hash(requirement.local_file_path)


class WheelBuildError(Error):

    """Failed to build one or more wheels"""

    def __init__(self, failures):
        super(WheelBuildError, self).__init__(self.__doc__)
        self.failures = failures


def _copy_file_if_missing(source_path, directory):
    base_name = os.path.basename(source_path)
    dest_path = os.path.join(directory, base_name)

    if os.path.isfile(dest_path):
        LOG.debug("Local wheel %s already exists", dest_path)
        return dest_path

    util.ensure_directory_exists(directory)
    shutil.copy(source_path, dest_path)

    return dest_path


class ResolvedRequirement(object):

    def __init__(self, name, version, source, is_direct=False, dependencies=None, extras=None):
        self.name = name
        self.version = version
        self.source = source
        self.is_direct = is_direct
        self.dependencies = dependencies or []
        self.extras = extras or []


class ResolvedRequirementSource(object):

    def __init__(self, url, sha256=None):
        self.url = url
        self.sha256 = sha256

    def is_local(self):
        return self._parse_url().scheme == 'file'

    def _parse_url(self):
        return urlcompat.urlparse(self.url)

    def get_file_name(self):
        return os.path.basename(self._get_path())

    def _get_path(self):
        return self._parse_url().path

    def get_name(self):
        stem = util.get_path_stem(self._get_path())
        return stem.replace("-", "_").replace(".", "_")

