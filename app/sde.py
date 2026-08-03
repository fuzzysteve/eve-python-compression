from dataclasses import dataclass, field

import pymysql
import pymysql.cursors

from app import config

REPROCESSING_SKILL_ATTRIBUTE_ID = 790


@dataclass
class OreData:
    type_id: int
    name: str
    volume_m3: float
    portion_size: int
    skill_type_id: int | None
    base_yields: dict[str, int] = field(default_factory=dict)


def get_connection() -> pymysql.connections.Connection:
    return pymysql.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,
    )


_ORE_METADATA_QUERY = """
    SELECT
        ct.compressedTypeID AS type_id,
        it.typeName AS name,
        it.volume AS volume_m3,
        it.portionSize AS portion_size,
        COALESCE(dta.valueInt, dta.valueFloat) AS skill_type_id
    FROM compressibleTypes ct
    JOIN invTypes it ON it.typeID = ct.compressedTypeID
    LEFT JOIN dgmTypeAttributes dta
        ON dta.typeID = ct.typeID AND dta.attributeID = %s
"""

_ORE_YIELDS_QUERY = """
    SELECT
        ct.compressedTypeID AS type_id,
        m.typeName AS mineral_name,
        itm.quantity AS quantity
    FROM compressibleTypes ct
    JOIN invTypeMaterials itm ON itm.typeID = ct.compressedTypeID
    JOIN invTypes m ON m.typeID = itm.materialTypeID
"""


def load_compressed_ore_data(conn: pymysql.connections.Connection) -> dict[str, OreData]:
    ores_by_id: dict[int, OreData] = {}

    with conn.cursor() as cursor:
        cursor.execute(_ORE_METADATA_QUERY, (REPROCESSING_SKILL_ATTRIBUTE_ID,))
        for row in cursor.fetchall():
            skill_type_id = row["skill_type_id"]
            ores_by_id[row["type_id"]] = OreData(
                type_id=row["type_id"],
                name=row["name"],
                volume_m3=float(row["volume_m3"]),
                portion_size=int(row["portion_size"]),
                skill_type_id=int(skill_type_id) if skill_type_id is not None else None,
            )

        cursor.execute(_ORE_YIELDS_QUERY)
        for row in cursor.fetchall():
            ore = ores_by_id.get(row["type_id"])
            if ore is not None:
                ore.base_yields[row["mineral_name"]] = int(row["quantity"])

    return {ore.name: ore for ore in ores_by_id.values()}
