import faultforge


def test_package_exposes_version():
    assert faultforge.__version__ == "0.1.0"
