"""What the source data looks like: the raw columns, and the US states the
map draws.

The raw files are CSV, one per year, as `generate` writes them. Replace
`generate` with whatever fetches your real data and keep this layout (or
change it here and in `ingest.TICKETS_SQL` together).
"""

from __future__ import annotations

# (column, DuckDB type) in file order. Every raw file has a header row.
RAW_COLUMNS = [
    ("ticket_id", "BIGINT"),
    ("opened_at", "TIMESTAMP"),
    ("resolved_at", "TIMESTAMP"),  # empty while the ticket is open
    ("product", "VARCHAR"),
    ("plan", "VARCHAR"),
    ("channel", "VARCHAR"),
    ("category", "VARCHAR"),
    ("severity", "INTEGER"),  # 1 low .. 4 critical
    ("state", "VARCHAR"),  # customer's state, USPS code
    ("escalated", "BOOLEAN"),
    ("satisfaction", "INTEGER"),  # 1..5 survey score; empty when the customer didn't answer
    ("refund_usd", "DOUBLE"),
    ("subject", "VARCHAR"),
    ("body", "VARCHAR"),
]

# USPS code -> (FIPS, name, 2020 Census resident population). The map joins
# on FIPS (us-atlas feature ids); per-capita rates divide by population.
STATES = {
    "AL": ("01", "Alabama", 5_024_279),
    "AK": ("02", "Alaska", 733_391),
    "AZ": ("04", "Arizona", 7_151_502),
    "AR": ("05", "Arkansas", 3_011_524),
    "CA": ("06", "California", 39_538_223),
    "CO": ("08", "Colorado", 5_773_714),
    "CT": ("09", "Connecticut", 3_605_944),
    "DE": ("10", "Delaware", 989_948),
    "DC": ("11", "District of Columbia", 689_545),
    "FL": ("12", "Florida", 21_538_187),
    "GA": ("13", "Georgia", 10_711_908),
    "HI": ("15", "Hawaii", 1_455_271),
    "ID": ("16", "Idaho", 1_839_106),
    "IL": ("17", "Illinois", 12_812_508),
    "IN": ("18", "Indiana", 6_785_528),
    "IA": ("19", "Iowa", 3_190_369),
    "KS": ("20", "Kansas", 2_937_880),
    "KY": ("21", "Kentucky", 4_505_836),
    "LA": ("22", "Louisiana", 4_657_757),
    "ME": ("23", "Maine", 1_362_359),
    "MD": ("24", "Maryland", 6_177_224),
    "MA": ("25", "Massachusetts", 7_029_917),
    "MI": ("26", "Michigan", 10_077_331),
    "MN": ("27", "Minnesota", 5_706_494),
    "MS": ("28", "Mississippi", 2_961_279),
    "MO": ("29", "Missouri", 6_154_913),
    "MT": ("30", "Montana", 1_084_225),
    "NE": ("31", "Nebraska", 1_961_504),
    "NV": ("32", "Nevada", 3_104_614),
    "NH": ("33", "New Hampshire", 1_377_529),
    "NJ": ("34", "New Jersey", 9_288_994),
    "NM": ("35", "New Mexico", 2_117_522),
    "NY": ("36", "New York", 20_201_249),
    "NC": ("37", "North Carolina", 10_439_388),
    "ND": ("38", "North Dakota", 779_094),
    "OH": ("39", "Ohio", 11_799_448),
    "OK": ("40", "Oklahoma", 3_959_353),
    "OR": ("41", "Oregon", 4_237_256),
    "PA": ("42", "Pennsylvania", 13_002_700),
    "RI": ("44", "Rhode Island", 1_097_379),
    "SC": ("45", "South Carolina", 5_118_425),
    "SD": ("46", "South Dakota", 886_667),
    "TN": ("47", "Tennessee", 6_910_840),
    "TX": ("48", "Texas", 29_145_505),
    "UT": ("49", "Utah", 3_271_616),
    "VT": ("50", "Vermont", 643_077),
    "VA": ("51", "Virginia", 8_631_393),
    "WA": ("53", "Washington", 7_705_281),
    "WV": ("54", "West Virginia", 1_793_716),
    "WI": ("55", "Wisconsin", 5_893_718),
    "WY": ("56", "Wyoming", 576_851),
}
