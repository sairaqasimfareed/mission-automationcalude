from pydantic import ValidationError

from src.models.enums import ProductionMode
from src.models.policy import PolicyComplianceReport, RiskLevel


# Premium Mode → Allowed
premium_report = PolicyComplianceReport(
    source_mode=ProductionMode.PREMIUM,
    upload_readiness=True,
    youtube_monetization_risk=RiskLevel.LOW,
    facebook_monetization_risk=RiskLevel.LOW,
)

print("Premium upload readiness:", premium_report.upload_readiness)


# Quick Mode → Allowed only when upload_readiness=False
quick_report = PolicyComplianceReport(
    source_mode=ProductionMode.QUICK,
    upload_readiness=False,
)

print("Quick upload readiness:", quick_report.upload_readiness)


# Quick Mode → Should FAIL when upload_readiness=True
try:
    PolicyComplianceReport(
        source_mode=ProductionMode.QUICK,
        upload_readiness=True,
    )
except ValidationError as error:
    print("✅ Invalid Quick Mode state successfully blocked.")
    print(error.errors()[0]["msg"])
else:
    raise AssertionError(
        "Quick Mode was incorrectly allowed to become upload-ready."
    )

print("Policy compliance tests completed successfully.")