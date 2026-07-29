from src.services.stock_search_service import (
    StockSearchService,
)


service = StockSearchService()

results = service.search(
    "Ancient underground tunnel"
)

print("Results:", len(results))

for item in results:

    print("Provider :", item.provider)
    print("Title    :", item.title)
    print("URL      :", item.file_url)
    print("License  :", item.license_type)
    print()

assert len(results) == 1

assert results[0].provider == "Dry Run"

assert (
    results[0].license_type
    == "royalty_free"
)

print(
    "Stock Search Service tests completed successfully."
)