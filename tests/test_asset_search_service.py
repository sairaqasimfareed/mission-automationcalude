from src.services.asset_search_service import (
    AssetSearchService,
    AssetType,
)

service = AssetSearchService()

results = service.search(
    AssetType.VIDEO,
    "Ancient underground tunnel",
)

print("Results:", len(results))

for item in results:

    print("Type      :", item.asset_type)
    print("Provider  :", item.provider)
    print("Title     :", item.title)
    print("URL       :", item.file_url)
    print("License   :", item.license_type)

assert len(results) == 1

assert results[0].asset_type == AssetType.VIDEO

assert results[0].provider == "Dry Run"

print("Asset Search Service tests completed successfully.")
