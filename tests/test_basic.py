import pytest

import nichecompass


def test_package_has_version():
    assert nichecompass.__version__ is not None
