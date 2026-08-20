from pydantic import ValidationError

from src.services.stock_search_service import (
    DryRunStockProvider,
    StockSearchRequest,
    StockSearchService,
)

request = StockSearchRequest(
    query=" cinematic ancient Rome ",
    page=1,
    per_page=10,
    orientation="landscape",
    minimum_duration_seconds=5.0,
    maximum_duration_seconds=20.0,
    minimum_width=1280,
    minimum_height=720,
)

assert request.query == "cinematic ancient Rome"


service = StockSearchService(
    providers=[
        DryRunStockProvider(),
    ]
)

results = service.search(request)

print("Providers:", service.available_providers())
print("Results:", len(results))
print("Title:", results[0].title)
print("File:", results[0].file_url)
print("License:", results[0].license_type)

assert service.available_providers() == [
    "Dry Run Stock",
]

assert len(results) == 1

asset = results[0]

assert asset.provider == "Dry Run Stock"
assert asset.provider_asset_id == ("dry-run-video-001")
assert asset.title == "cinematic ancient Rome"
assert asset.file_url.endswith(".mp4")
assert asset.license_type == "royalty_free"
assert asset.attribution_required is False
assert asset.duration_seconds == 8.0
assert asset.resolution == "1920x1080"
assert asset.aspect_ratio == "16:9"
assert asset.metadata["dry_run"] == "true"


try:
    StockSearchRequest(
        query=" ",
    )
except ValidationError:
    print("Empty stock query successfully blocked.")
else:
    raise AssertionError("Empty stock query should fail.")


print("Stock Search Service tests completed successfully.")
