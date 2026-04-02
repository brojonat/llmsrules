---
name: redfin-api
description: Interact with Redfin's unofficial stingray API for property search, listing data, AVM estimates, and property history. Use when writing code to search listings, fetch property details, parse Redfin responses, or build GISCSV queries.
---

# Redfin API

Redfin exposes an unofficial JSON API at `https://www.redfin.com/stingray/`. All
requests are HTTP GET. Responses are prefixed with `{}& ` (4 bytes) before valid
JSON — always strip this prefix before parsing.

## Authentication & Headers

- **User-Agent** header is required (use a current Chrome UA string)
- Optional cookies for authenticated access:
  - `RF_ACCESS_LEVEL`, `RF_AUTH`, `RF_W_AUTH`, `RF_SECURE_AUTH`, `RF_PARTY_ID`
- Add rate-limiting delays between requests to avoid being blocked

## Response Format

Every endpoint returns this wrapper:

```json
{
  "version": 1,
  "errorMessage": "Success",
  "resultCode": 0,
  "payload": { ... }
}
```

`resultCode == 0` and `errorMessage == "Success"` indicates success. The
`payload` structure varies by endpoint.

## Core Workflows

### 1. Search for Listings by Zip Code / Location

**Step 1: Location autocomplete** to get a region ID.

```
GET /stingray/do/location-autocomplete?location={query}&v=2
```

Response payload:
```json
{
  "sections": [{ "rows": [{ "id": "2_12345", "type": "2", "name": "92708", ... }] }],
  "exactMatch": { "id": "2_12345", ... }
}
```

The `id` field is `{region_type}_{region_id}`. Split on `_` to extract both.

**Step 2: GIS CSV download** to get property listings for that region.

```
GET /stingray/api/gis-csv?region_id={id}&region_type={type}&...
```

Returns CSV data (not JSON — no `{}& ` prefix). The CSV has:
- Row 0: headers (look for `URL` column)
- Row 1: MLS disclaimer text ("In accordance with local MLS rules...")
- Rows 2+: property data

Extract the URL column to get Redfin property URLs for further querying.

### 2. Get Property IDs from a URL

```
GET /stingray/api/home/details/initialInfo?path={redfin_path}
```

Where `path` is the URL path portion (e.g., `/CA/Fountain-Valley/12345-Main-St-92708/home/12345678`).

Payload:
```json
{
  "propertyId": 12345678,
  "listingId": 234567890,
  "latLong": { "latitude": 33.71, "longitude": -117.95 }
}
```

### 3. Get Property Details

Most detail endpoints live under `/stingray/api/home/details/`. Some require
just `propertyId`, others require both `propertyId` and `listingId`.

For property-only endpoints, add `accessLevel=1` and optionally `pageType=3`.

## Endpoint Reference

### URL-based (pass `path` parameter)

| Endpoint | Path |
|---|---|
| Initial Info | `api/home/details/initialInfo` |
| Page Tags | `api/home/details/v1/pagetagsinfo` |
| Primary Region | `api/home/details/primaryRegionInfo` |

### Search

| Endpoint | Path | Key Params |
|---|---|---|
| Location Autocomplete | `do/location-autocomplete` | `location`, `v=2` |
| GIS CSV | `api/gis-csv` | `region_id`, `region_type`, filters (see below) |

### Property ID Only (`propertyId` param)

| Endpoint | Path | Page Type |
|---|---|---|
| Below The Fold (MLS) | `api/home/details/belowTheFold` | 3 |
| Hood Photos | `api/home/details/hood-photos` | — |
| More Resources | `api/home/details/moreResourcesInfo` | — |
| Page Header | `api/home/details/homeDetailsPageHeaderInfo` | — |
| Property Comments | `api/v1/home/details/propertyCommentsInfo` | — |
| Building Details | `api/building/details-page/v1` | — |
| Owner Estimate | `api/home/details/owner-estimate` | — |
| Claimed Seller Data | `api/home/details/claimedHomeSellerData` | — |
| Cost of Ownership | `do/api/costOfHomeOwnershipDetails` | — |

### Listing ID Only (`listingId` param)

| Endpoint | Path |
|---|---|
| Floor Plans | `api/home/details/listing/floorplans` |
| Tour Date Picker | `do/tourlist/getDatePickerData` |

### Table ID (`tableId` param)

| Endpoint | Path | Extra Params |
|---|---|---|
| Shared Region | `api/region/shared-region-info` | `regionTypeId=2`, `mapPageTypeId=1` |

### Full Property Details (`propertyId` + `listingId` params)

| Endpoint | Path | Page Type |
|---|---|---|
| Similar Listings | `api/home/details/similars/listings` | — |
| Similar Sold | `api/home/details/similars/solds` | — |
| Nearby Homes | `api/home/details/nearbyhomes` | — |
| Above The Fold | `api/home/details/aboveTheFold` | — |
| Property Parcel | `api/home/details/propertyParcelInfo` | 3 |
| Activity/History | `api/home/details/activityInfo` | — |
| Off-Market Info | `api/home/details/customerConversionInfo/offMarket` | 3 |
| Rental Estimate | `api/home/details/rental-estimate` | — |
| AVM Historical | `api/home/details/avmHistoricalData` | — |
| Info Panel | `api/home/details/mainHouseInfoPanelInfo` | — |
| Description | `api/home/details/descriptiveParagraph` | — |
| AVM Details | `api/home/details/avm` | — |
| Tour Insights | `api/home/details/tourInsights` | 3 |
| Stats | `api/home/details/stats` | also needs `regionId` |

## GISCSV Default Parameters

These defaults return a broad set of listings for a given region. Override
`region_id` and `region_type` per search.

```python
DEFAULT_GISCSV_PARAMS = {
    "al": "3",
    "num_homes": "350",
    "ord": "redfin-recommended-asc",
    "page_number": "1",
    "region_id": "",          # required — from location autocomplete
    "region_type": "2",       # 2 = zipcode
    "sf": "1,2,5,6,7",       # property sub-filters
    "status": "9",            # 9 = all statuses
    "uipt": "1,2,3,4,5,6,7,8",  # all property types
    "v": "8",
    # boolean filters (all false for broadest results)
    "has_pool": "false",
    "has_parking": "false",
    "has_laundry_facility": "false",
    "has_laundry_hookups": "false",
    "has_dishwasher": "false",
    "has_att_fiber": "false",
    "has_deal": "false",
    "has_short_term_lease": "false",
    "include_pending_homes": "false",
    "isRentals": "false",
    "is_furnished": "false",
    "is_income_restricted": "false",
    "is_senior_living": "false",
    "pool": "false",
    "travel_with_traffic": "false",
    "travel_within_region": "false",
    "utilities_included": "false",
}
```

### Filtering for Single-Family Homes Only

To restrict to single-family homes (relevant for this project):
- Set `uipt=1` (single family only, instead of `1,2,3,4,5,6,7,8`)
- Set `sf=1,2,5,6,7` (keeps the default sub-filters)

### Property Type Codes (`uipt`)

| Code | Type |
|---|---|
| 1 | Single Family |
| 2 | Condo |
| 3 | Townhouse |
| 4 | Multi-Family |
| 5 | Land |
| 6 | Mobile/Manufactured |
| 7 | Co-op |
| 8 | Other |

## Parsing Response Payloads

Redfin payloads are deeply nested. Use JMESPath expressions (or equivalent
dictionary traversal) to extract data.

### From InitialInfo Payload

| Field | JMESPath |
|---|---|
| Property ID | `propertyId` |
| Listing ID | `listingId` |
| Latitude | `latLong.latitude` |
| Longitude | `latLong.longitude` |

### From BelowTheFold (MLS) Payload

| Field | JMESPath |
|---|---|
| Zip Code | `publicRecordsInfo.addressInfo.zip` |
| City | `publicRecordsInfo.addressInfo.city` |
| State | `publicRecordsInfo.addressInfo.state` |
| Image URLs | `propertyHistoryInfo.mediaBrowserInfoBySourceId.*.photos[].photoUrls.nonFullScreenPhotoUrlCompressed` |
| Thumbnail URLs | `propertyHistoryInfo.mediaBrowserInfoBySourceId.*.photos[].thumbnailData.thumbnailUrl` |
| Realtor Attribution | `propertyHistoryInfo.mediaBrowserInfoBySourceId.*.photoAttribution \| [0]` |
| Event Count | `length(propertyHistoryInfo.events)` |
| Event Price | `propertyHistoryInfo.events[N].price` |
| Event Description | `propertyHistoryInfo.events[N].eventDescription` |
| Event Source | `propertyHistoryInfo.events[N].source` |
| Event Source ID | `propertyHistoryInfo.events[N].sourceId` |
| Event Date | `propertyHistoryInfo.events[N].eventDate` (Unix ms) |

### Realtor Name Parsing

The `photoAttribution` field looks like `"Listed by Jane Smith • Acme Realty."`.
Split on `•`, trim whitespace, strip `"Listed by "` prefix from part 0, strip
trailing `.` from part 1.

### Event Date Handling

Event dates are Unix timestamps in **milliseconds**. Convert:
`datetime.fromtimestamp(event_date / 1000)` (Python) or
`time.Unix(0, event_date * int64(time.Millisecond))` (Go).

## Most Useful Endpoints for Home Buying

For property evaluation, these three give you the most value:

1. **InitialInfo** — property/listing IDs, lat/long
2. **BelowTheFold** — address, property history (price changes), images, realtor info
3. **AVMDetails** — Redfin's automated valuation model estimate

Additional high-value endpoints:
- **SimilarSold** — recent comparable sales
- **SimilarListings** — competing listings
- **CostOfHomeOwnership** — estimated monthly costs breakdown
- **Activity** — showing activity, saves, views
- **Stats** — market statistics for the region

## Implementation Notes

### Response Prefix Stripping

Every response (except GISCSV which returns raw CSV) is prefixed with `{}& `
(exactly 4 bytes). Strip before JSON parsing:

```go
// Go
jsonBytes := responseBytes[4:]
```

```python
# Python
data = json.loads(response.text[4:])
```

### Rate Limiting

Add delays between requests (the gredfin project uses a configurable interval,
typically a few seconds). Redfin will block aggressive scraping.

### Error Handling

Always check both the HTTP status code AND the `resultCode`/`errorMessage`
fields in the JSON response. A 200 HTTP status can still contain an error in the
Redfin response body.

### Hash-Based Deduplication

When polling properties over time, hash the payload bytes (MD5) and skip
re-processing if unchanged from the last scrape.
