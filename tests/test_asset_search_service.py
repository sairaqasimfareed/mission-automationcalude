from src.services.asset_search_service import (
    AssetSearchService,
    AssetType,
)
from src.services.stock_search_service import (
    DryRunStockProvider,
    StockSearchService,
)


stock_service = StockSearchService(
    providers=[
        DryRunStockProvider(),
    ]
)

service = AssetSearchService(
    stock_search_service=stock_service,
)


results = service.search(
    asset_type=AssetType.VIDEO,
    query="ancient Roman streets",
    limit=5,
)

print("Result count:", len(results))
print("Provider:", results[0].provider)
print("Title:", results[0].title)
print("File URL:", results[0].file_url)
print("License:", results[0].license_type)

assert len(results) == 1

asset = results[0]

assert asset.asset_type == AssetType.VIDEO
assert asset.provider == "Dry Run Stock"
assert asset.provider_asset_id == (
    "dry-run-video-001"
)
assert asset.title == "ancient Roman streets"
assert asset.file_url.endswith(".mp4")
assert asset.license_type == "royalty_free"
assert asset.attribution_required is False
assert asset.duration_seconds == 8.0
assert asset.resolution == "1920x1080"
assert asset.aspect_ratio == "16:9"
assert asset.metadata is not None
assert asset.metadata["dry_run"] == "true"


empty_results = service.search(
    asset_type=AssetType.IMAGE,
    query="Roman temple",
)

assert empty_results == []


try:
    service.search(
        asset_type=AssetType.VIDEO,
        query=" ",
    )
except ValueError:
    print("Empty asset query successfully blocked.")
else:
    raise AssertionError(
        "Empty asset query should fail."
    )


try:
    service.search(
        asset_type=AssetType.VIDEO,
        query="Roman city",
        limit=0,
    )
except ValueError:
    print("Invalid asset limit successfully blocked.")
else:
    raise AssertionError(
        "Invalid asset limit should fail."
    )


print(
    "Asset Search Service tests completed successfully."
)