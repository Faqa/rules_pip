#!/usr/bin/env python
import argparse
import json
import os
import textwrap


def main():
    args = parse_args()
    lock_file = load_requirements(args.requirements_lock_file)

    BzlFileGenerator(lock_file, args.rules_pip_repo).generate(args.bzl_file_path)
    AliasPackageGenerator(lock_file, args.rules_pip_repo).generate(args.repository_dir)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("requirements_lock_file")
    parser.add_argument("bzl_file_path")
    parser.add_argument("repository_dir")
    parser.add_argument("rules_pip_repo")
    return parser.parse_args()


def load_requirements(path):
    with open(path) as requirements_lock_file:
        return json.load(requirements_lock_file)


class BzlFileGenerator(object):

    def __init__(self, lock_file, rules_pip_repo):
        self.lock_file = lock_file
        self.rules_pip_repo = rules_pip_repo

    @property
    def sources(self):
        return self.lock_file["sources"]

    @property
    def local_wheels_package(self):
        return self.lock_file["local_wheels_package"]

    def generate(self, path):
        write_file(path, self._generate_content())

    def _generate_content(self):
        return textwrap.dedent("""
            load("@{rules_pip_repo}//rules:wheel.bzl", "local_wheel", "remote_wheel")

            {pip_install_macro}
        """).strip().format(
            rules_pip_repo=self.rules_pip_repo,
            pip_install_macro=self._generate_pip_install_macro(),
        )

    def _generate_pip_install_macro(self):
        pip_repo_rules = "\n".join(
            indent_block(rule, 1)
            for rule in self._generate_all_pip_repo_rules()
        )

        return textwrap.dedent("""
            def pip_install():
            {rules}
        """).strip().format(
            rules=pip_repo_rules,
        )

    def _generate_all_pip_repo_rules(self):
        for name, source in self.sources.items():
            if "url" in source:
                yield self._generate_remote_wheel_rule(name, source)
            else:
                yield self._generate_local_wheel_rule(name, source)

    def _generate_remote_wheel_rule(self, name, source):
        return textwrap.dedent("""
            if not native.existing_rule("{name}"):
                remote_wheel(
                    name = "{name}",
                    url = "{url}",
                    sha256 = "{sha256}",
                )
        """).strip().format(
            name=get_source_repo_name(name),
            url=source["url"],
            sha256=source.get("sha256", ""),
        )

    def _generate_local_wheel_rule(self, name, source):
        return textwrap.dedent("""
            if not native.existing_rule("{name}"):
                local_wheel(
                    name = "{name}",
                    wheel = "{package}:{file}",
                )
        """).strip().format(
            name=get_source_repo_name(name),
            package=self.local_wheels_package,
            file=source["file"],
        )


def get_source_repo_name(source_name):
    return "pip__{}".format(source_name)


def indent_block(string, level):
    lines = string.splitlines()
    return "\n".join(indent_line(line, level) for line in lines)


def indent_line(line, level):
    return "{}{}".format((level * 4 * " "), line)


class AliasPackageGenerator(object):

    def __init__(self, lock_file, rules_pip_repo):
        self.lock_file = lock_file
        self.rules_pip_repo = rules_pip_repo

    @property
    def environments(self):
        return self.lock_file["environments"]

    def generate(self, repository_dir):
        requirement_tree = self._build_requirement_tree()

        for name, python_subtree in requirement_tree.items():
            self._generate_package_for_requirement(
                repository_dir,
                name,
                python_subtree,
            )

    def _build_requirement_tree(self):
        tree = {}

        for environment_name, environment_details in self.environments.items():
            python_version = environment_details["python_version"]
            sys_platform = environment_details["sys_platform"]
            bazel_platform = _convert_sys_platform_to_bazel(sys_platform)
            requirements = environment_details["requirements"]

            for requirement_name, requirement_details in requirements.items():
                normalized_name = _normalize_distribution_name(requirement_name)

                tree.setdefault(
                    normalized_name, {}
                ).setdefault(
                    python_version, {}
                )[bazel_platform] = requirement_details

        return tree

    def _generate_package_for_requirement(
        self,
        repository_dir,
        requirement_name,
        python_subtree,
    ):
        package_dir = os.path.join(repository_dir, requirement_name)
        os.makedirs(package_dir)

        build_file_path = os.path.join(package_dir, "BUILD")
        build_rules = self._generate_rules_for_requirement(
            requirement_name,
            python_subtree,
        )
        build_file_content = self._generate_build_file_content(build_rules)

        write_file(build_file_path, build_file_content)

        repos_file_path = os.path.join(package_dir, "repos.bzl")
        repos_file_content = self._generate_repos_file_content(python_subtree)

        write_file(repos_file_path, repos_file_content)

    def _generate_build_file_content(self, build_rules):
        return textwrap.dedent("\n".join(build_rules))

    def _generate_rules_for_requirement(self, requirement_name, python_subtree):
        top_alias = SelectAlias(requirement_name)

        # We want to make the top alias "visible" only if the package is specified
        # in the requirements.txt file (i.e. has `is_direct=True` field in the lock
        # file). Since there's an `is_direct` key for each python_version/platform,
        # we're going to set the visibility  to public if any of those is True.
        visibility = "//:__subpackages__"

        for python_version, platform_subtree in python_subtree.items():
            for platform, requirement_details in platform_subtree.items():
                yield self._generate_py_library(
                    requirement_details,
                    python_version,
                    platform,
                )
                if requirement_details["is_direct"]:
                    visibility = "//visibility:public"

            version_alias = self._generate_python_version_alias(
                python_version,
                platform_subtree,
            )

            yield str(version_alias)

            python_version_label = _make_python_version_label(python_version)
            top_alias.actual[python_version_label] = version_alias.name

        top_alias.visibility = visibility
        yield str(top_alias)

    def _generate_py_library(self, requirement_details, python_version, platform):
        name = _make_environment_specific_alias(
            python_version,
            platform,
        )
        deps = list(self._generate_dependency_labels(requirement_details))

        return textwrap.dedent("""
            py_library(
                name = "{name}",
                deps = {deps},
            )
        """).strip().format(
            name=name,
            deps=deps,
        )

    def _generate_dependency_labels(self, requirement_details):
        yield _make_source_lib_label(requirement_details["source"])
        for dep in requirement_details["dependencies"]:
            dep_name = _normalize_distribution_name(dep)
            yield _make_package_label(dep_name)

    def _generate_python_version_alias(self, python_version, platform_subtree):
        alias = SelectAlias(
            _make_python_specific_alias(python_version)
        )

        for platform in platform_subtree:
            bazel_platform = _convert_sys_platform_to_bazel(platform)

            platform_label = _make_platform_label(self.rules_pip_repo, bazel_platform)

            alias.actual[platform_label] = _make_environment_specific_alias(
                python_version,
                platform,
            )

        return alias

    def _generate_repos_file_content(self, python_subtree):
        return "\n\n".join(self._generate_repo_variables(python_subtree))

    def _generate_repo_variables(self, python_subtree):
        all_seen = set()

        for python_version, platform_subtree in python_subtree.items():
            seen_for_python_version = set()

            for platform, requirement_details in platform_subtree.items():
                name = _make_environment_specific_alias(python_version, platform)
                repo_label = _make_source_repo_label(requirement_details["source"])

                yield _make_variable_definition(name, repo_label)

                seen_for_python_version.add(repo_label)

            if len(seen_for_python_version) == 1:
                name = _make_python_specific_alias(python_version)
                yield _make_variable_definition(name, list(seen_for_python_version)[0])

            all_seen.update(seen_for_python_version)

        if len(all_seen) == 1:
            yield _make_variable_definition("all", list(all_seen)[0])


def _normalize_distribution_name(name):
    return name.lower().replace("-", "_")


def _make_python_specific_alias(python_version):
    return "py{}".format(python_version)


def _make_environment_specific_alias(python_version, platform):
    return "py{}_{}".format(python_version, platform)


def _make_python_version_label(version):
    return "@bazel_tools//tools/python:PY{version}".format(version=version)


def _make_platform_label(rules_pip_repo, platform):
    return "@{rules_pip_repo}//platforms:{platform}".format(
        rules_pip_repo=rules_pip_repo,
        platform=platform,
    )


def _make_source_lib_label(source_name):
    return "{}//:lib".format(_make_source_repo_label(source_name))


def _make_source_repo_label(source_name):
    return "@{}".format(get_source_repo_name(source_name))


def _make_package_label(name):
    return "//{}".format(name)


def _make_variable_definition(name, value):
    return '{} = "{}"'.format(name, value)


def _convert_sys_platform_to_bazel(sys_platform):
    if sys_platform == "darwin":
        return "osx"

    if "linux" in sys_platform:
        return "linux"

    return sys_platform


class SelectAlias(object):

    def __init__(self, name):
        self.name = name
        self.actual = {}
        self.visibility = "//visibility:private"

    def __str__(self):
        return textwrap.dedent("""
            alias(
                name = "{name}",
                actual = select({actual}),
                visibility = ["{visibility}"],
            )
        """).strip().format(
            name=self.name,
            actual=self.actual,
            visibility=self.visibility,
        )


def write_file(path, contents):
    with open(path, mode="w") as bzl_file:
        bzl_file.write(contents)


if __name__ == "__main__":
    main()
