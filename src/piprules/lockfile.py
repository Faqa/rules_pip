import errno
import json
import logging
import os
import sys

import schematics

from piprules import util


LOG = logging.getLogger(__name__)


class _SortedListType(schematics.types.ListType):

    def convert(self, value, context=None):
        value = super(_SortedListType, self).convert(value, context=context)
        return sorted(value)


class Requirement(schematics.models.Model):

    version = schematics.types.StringType(required=True)
    is_direct = schematics.types.BooleanType(required=True)
    source = schematics.types.StringType(required=True)
    dependencies = _SortedListType(
        schematics.types.StringType,
        default=[],
    )
    extras = _SortedListType(
        schematics.types.StringType,
        default=[],
    )


class Environment(schematics.models.Model):

    sys_platform = schematics.types.StringType()
    python_version = schematics.types.IntType(choices=[2, 3])
    requirements = schematics.types.DictType(
        schematics.types.ModelType(Requirement),
        default={},
    )

    @classmethod
    def from_current(cls):
        environment = cls()
        environment.set_to_current()
        return environment

    @property
    def name(self):
        return "{sys_platform}_py{python_version}".format(**self.to_primitive())

    def set_to_current(self):
        self.sys_platform = sys.platform
        self.python_version = sys.version_info.major

    def matches_current(self):
        return self == _CURRENT_ENVIRONMENT

    def __eq__(self, other):
        return (
            self.sys_platform == other.sys_platform and
            self.python_version == other.python_version
        )

    def __hash__(self):
        return hash((
            self.sys_platform,
            self.python_version,
        ))


_CURRENT_ENVIRONMENT = Environment.from_current()


class Source(schematics.models.Model):

    # TODO validate that at least one of these two is set
    url = schematics.types.URLType(serialize_when_none=False)
    file = schematics.types.StringType(serialize_when_none=False)
    sha256 = schematics.types.StringType(serialize_when_none=False)

    def __eq__(self, other):
        return (
            self.url == other.url and
            self.file == other.file and
            self.sha256 == other.sha256
        )


class LockFile(schematics.models.Model):

    environments = schematics.types.DictType(
        schematics.types.ModelType(Environment),
        default={},
    )
    sources = schematics.types.DictType(
        schematics.types.ModelType(Source),
        default={},
    )
    local_wheels_package = schematics.types.StringType()

    @classmethod
    def load(cls, path):
        LOG.info('Reading requirements lock file %s', path)

        with open(path) as lock_file:
            json_string = lock_file.read()

        return cls.from_json(json_string)

    @classmethod
    def from_json(cls, json_string):
        return cls(json.loads(json_string))

    def dump(self, path):
        LOG.info('Writing requirements lock file to %s', path)

        util.ensure_directory_exists(os.path.dirname(path))

        json_string = self.to_json()

        with open(path, mode='w') as lock_file:
            lock_file.write(json_string)

    def to_json(self):
        return json.dumps(self.to_primitive(), indent=2, sort_keys=True)

    def update_requirements_for_current_environment(self, resolved_requirements):
        new_requirements = {}

        for resolved_requirement in resolved_requirements:
            resolved_source = resolved_requirement.source
            source_name = resolved_source.get_name()

            if resolved_source.is_local():
                new_source = Source(dict(
                    file=resolved_source.get_file_name(),
                ))
            else:
                new_source = Source(dict(
                    url=resolved_source.url,
                    sha256=resolved_source.sha256,
                ))

            self._warn_if_source_is_changing(source_name, new_source)
            self.sources[source_name] = new_source

            new_requirements[resolved_requirement.name] = Requirement(dict(
                version=resolved_requirement.version,
                is_direct=resolved_requirement.is_direct,
                source=source_name,
                dependencies=resolved_requirement.dependencies,
                extras=resolved_requirement.extras,
            ))

        self._get_or_create_current_environment().requirements = new_requirements
        self._purge_unused_sources()

    def _warn_if_source_is_changing(self, source_name, new_source):
        try:
            existing_source = self.sources[source_name]
        except KeyError:
            return

        if new_source != existing_source:
            LOG.warning("Changing source %s in lock file", source_name)

    def _get_or_create_current_environment(self):
        return self.environments.setdefault(
            _CURRENT_ENVIRONMENT.name,
            _CURRENT_ENVIRONMENT
        )

    def _purge_unused_sources(self):
        self.sources = {
            key: source
            for key, source in self.sources.items()
            if self._is_source_used(key)
        }

    def _is_source_used(self, source_key):
        return any(
            requirement.source == source_key
            for environment in self.environments.values()
            for requirement in environment.requirements.values()
        )

    def get_requirements_for_current_environment(self):
        return self._get_or_create_current_environment().requirements


def load(path, create_if_missing=True):
    try:
        return LockFile.load(path)
    except IOError as err:
        if create_if_missing and err.errno == errno.ENOENT:
            return LockFile()
        raise err
