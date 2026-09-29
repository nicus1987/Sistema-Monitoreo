import pytest

from monitoreo.service import DEFAULT_CONFIG_DIR, MonitoringService


@pytest.fixture
def service():
    return MonitoringService(DEFAULT_CONFIG_DIR)
