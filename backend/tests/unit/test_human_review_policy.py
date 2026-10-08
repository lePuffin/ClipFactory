from unittest.mock import create_autospec
from uuid import uuid4

import pytest

from clipfactory.infrastructure.settings_validation import PublishingSettings
from clipfactory.publishing.approval import ApprovalService
from clipfactory.publishing.service import PublishService


@pytest.mark.unit
@pytest.mark.req("CF-REQ-459")
def test_quality_rollout_requires_explicit_review_by_default():
    settings = PublishingSettings()
    assert settings.approval_required
    assert not settings.auto_publish_enabled


@pytest.mark.unit
@pytest.mark.req("CF-REQ-460")
@pytest.mark.asyncio
async def test_legacy_timeout_cannot_publish_without_accepted_benchmark():
    class Repository:
        def resolve_approval(self, *args):
            raise AssertionError("Approval must not be resolved")

    publisher = create_autospec(PublishService, instance=True)
    service = ApprovalService(Repository(), publisher, clock=lambda: None)
    with pytest.raises(RuntimeError, match="benchmark"):
        await service.approve(uuid4(), approved_by="auto_timeout")
    publisher.execute.assert_not_awaited()
