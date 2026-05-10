"""Role exports for the active source acquisition flow."""

from whale.ingest.usecases.roles.polling_acquisition_role import (
    PollingAcquisitionRole,
    PollingAcquisitionSession,
)
from whale.ingest.usecases.roles.subscription_acquisition_role import (
    SubscriptionAcquisitionRole,
    SubscriptionAcquisitionSession,
)

__all__ = [
    "PollingAcquisitionRole",
    "PollingAcquisitionSession",
    "SubscriptionAcquisitionRole",
    "SubscriptionAcquisitionSession",
]
