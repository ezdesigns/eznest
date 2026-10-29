"""Whether this tree is an installed build.

The source checkout keeps INSTALLED false. The container image replaces this
module at build time. Frozen applications are installed builds as well.
"""
INSTALLED = False
