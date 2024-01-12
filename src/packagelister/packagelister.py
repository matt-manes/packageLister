import ast
import importlib.metadata
import sys
from dataclasses import dataclass

from pathier import Pathier, Pathish
from printbuddies import ProgBar
from typing_extensions import Self

packages_distributions = importlib.metadata.packages_distributions()


def is_builtin(package_name: str) -> bool:
    """Returns whether `package_name` is a standard library module or not."""
    return package_name in sys.stdlib_module_names


@dataclass
class Package:
    """Dataclass representing an imported package.

    #### Fields:
    * `name: str`
    * `distribution_name: str | None` - the name used to `pip install`, sometimes this differs from `name`
    * `version: str | None`
    * `builtin: bool` - whether this is a standard library package or not"""

    name: str
    distribution_name: str | None
    version: str | None
    builtin: bool

    def format_requirement(self, version_specifier: str):
        """Returns a string of the form `{self.distribution_name}{version_specifier}{self.version}`.
        e.g for this package: `"packagelister>=2.0.0"`"""
        return f"{self.distribution_name}{version_specifier}{self.version}"

    @classmethod
    def from_name(cls, package_name: str) -> Self:
        """Returns a `Package` instance from the package name.

        Will attempt to determine the other class fields."""
        distributions = packages_distributions.get(package_name)
        if distributions:
            distribution_name = distributions[0]
            version = importlib.metadata.version(distribution_name)
        else:
            distribution_name = None
            version = None
        return cls(package_name, distribution_name, version, is_builtin(package_name))


class PackageList(list[Package]):
    """A subclass of `list` to add convenience methods when working with a list of `packagelister.Package` objects."""

    @property
    def names(self) -> list[str]:
        """Returns a list of `Package.name` strings."""
        return [package.name for package in self]

    @property
    def third_party(self) -> Self:
        """Returns a `PackageList` instance for the third party packages in this list."""
        return self.__class__(
            [
                package
                for package in self
                if not package.builtin and package.distribution_name
            ]
        )

    @property
    def builtin(self) -> Self:
        """Returns a `PackageList` instance for the standard library packages in this list."""
        return self.__class__([package for package in self if package.builtin])


@dataclass
class File:
    """Dataclass representing a scanned file and its list of imported packages.

    #### Fields:
    * `path: Pathier` - Pathier object representing the path to this file
    * `packages: packagelister.PackageList` - List of Package objects imported by this file
    """

    path: Pathier
    packages: PackageList


@dataclass
class Project:
    """Dataclass representing a directory that's had its files scanned for imports.

    #### Fields:
    * `files: list[packagelister.File]`"""

    files: list[File]

    @property
    def packages(self) -> PackageList:
        """Returns a `packagelister.PackageList` object for this instance with no duplicates."""
        packages = []
        for file in self.files:
            for package in file.packages:
                if package not in packages:
                    packages.append(package)
        return PackageList(sorted(packages, key=lambda p: p.name))

    @property
    def requirements(self) -> PackageList:
        """Returns a `packagelister.PackageList` object of third party packages used by this project."""
        return self.packages.third_party

    def get_formatted_requirements(
        self, version_specifier: str | None = None
    ) -> list[str]:
        """Returns a list of formatted requirements (third party packages) using `version_specifier` (`==`,`>=`, `<=`, etc.).

        If no `version_specifier` is given, the returned list will just be package names.
        """
        return [
            requirement.format_requirement(version_specifier)
            if version_specifier
            else requirement.distribution_name or requirement.name
            for requirement in self.requirements
        ]

    def get_files_by_package(self) -> dict[str, list[Pathier]]:
        """Returns a dictionary where the keys are package names and the values are lists of files that import the package."""
        files_by_package = {}
        for package in self.packages:
            for file in self.files:
                name = package.name
                if name in file.packages.names:
                    if name not in files_by_package:
                        files_by_package[name] = [file.path]
                    else:
                        files_by_package[name].append(file.path)
        return files_by_package


def get_package_names_from_source(source: str) -> list[str]:
    """Scan `source` and extract the names of imported packages/modules."""
    tree = ast.parse(source)
    packages = []
    for node in ast.walk(tree):
        type_ = type(node)
        package = ""
        if type_ == ast.Import:
            package = node.names[0].name  # type: ignore
        elif type_ == ast.ImportFrom:
            package = node.module  # type: ignore
        if package:
            if "." in package:
                package = package[: package.find(".")]
            packages.append(package)
    return sorted(list(set(packages)))


def scan_file(file: Pathish) -> File:
    """Scan `file` for imports and return a `packagelister.File` instance."""
    file = Pathier(file) if not type(file) == Pathier else file
    source = file.read_text(encoding="utf-8")
    packages = get_package_names_from_source(source)
    used_packages = PackageList(
        [
            Package.from_name(package)
            for package in packages
            if package
            not in file.parts  # don't want to pick up modules in the scanned directory
        ]
    )
    return File(file, used_packages)


def scan_dir(path: Pathish) -> Project:
    """Recursively scan `*.py` files in `path` for imports and return a `packagelister.Project` instance."""
    path = Pathier(path) if not type(path) == Pathier else path
    files = list(path.rglob("*.py"))
    print(f"Scanning {path}...")
    with ProgBar(len(files)) as bar:
        project = Project(
            [bar.display(return_object=scan_file(file)) for file in files]
        )
    return project
