load("//rules:wheel.bzl", "remote_wheel")
load("@bazel_tools//tools/build_defs/repo:git.bzl", "git_repository")

def pip_rules_dependencies():
    _remote_wheel(
        name = "pip",
        url = "https://files.pythonhosted.org/packages/30/db/9e38760b32e3e7f40cce46dd5fb107b8c73840df38f0046d8e6514e675a1/pip-19.2.3-py2.py3-none-any.whl",
        sha256 = "340a0ba40fdeb16413914c0fcd8e0b4ebb0bf39a900ec80e11c05d836c05103f",
    )

    _remote_wheel(
        name = "schematics",
        url = "https://files.pythonhosted.org/packages/97/2f/2c5f0dc4dab5e5ca54e4d783f7f618bfc65d8788771876713d42eb8515aa/schematics-2.1.0-py2.py3-none-any.whl",
        sha256 = "8fcc6182606fd0b24410a1dbb066d9bbddbe8da9c9509f47b743495706239283",
    )

    _remote_wheel(
        name = "setuptools",
        url = "https://files.pythonhosted.org/packages/96/06/c8ee69628191285ddddffb277bd5abdf769166e7a14b867c2a172f0175b1/setuptools-40.4.3-py2.py3-none-any.whl",
        sha256 = "ce4137d58b444bac11a31d4e0c1805c69d89e8ed4e91fde1999674ecc2f6f9ff",
    )

    _remote_wheel(
        name = "wheel",
        url = "https://files.pythonhosted.org/packages/fc/e9/05316a1eec70c2bfc1c823a259546475bd7636ba6d27ec80575da523bc34/wheel-0.32.1-py2.py3-none-any.whl",
        sha256 = "9fa1f772f1a2df2bd00ddb4fa57e1cc349301e1facb98fbe62329803a9ff1196",
    )

    _ensure_rule_exists(
        git_repository,
        name = "bazel_skylib",
        remote = "https://github.com/bazelbuild/bazel-skylib.git",
        tag = "0.5.0",
    )

def _remote_wheel(name, url, sha256):
    _ensure_rule_exists(
        remote_wheel,
        name = "pip_rules__%s" % name,
        url = url,
        sha256 = sha256,
    )

def _ensure_rule_exists(rule_type, name, **kwargs):
    if name not in native.existing_rules():
        rule_type(name = name, **kwargs)
