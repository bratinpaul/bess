"""Seed the settlement node the arbitrage data pack prices at (battery_master.price_node).

    python 2026_10_15_dam_price_node.py            # rehearsal: insert, verify, ROLLBACK
    python 2026_10_15_dam_price_node.py --commit   # for real

BESS DESIGN/BESS_Arbitrage_DataPack/dam_price.csv quotes every price at node_code NODE-SITE01. The pack's own seed
ties that node to site_code 'SITE-01', which does not exist here, so price_node stayed empty. The pack is anchored to
the demo site / BESS-01, i.e. our KOL-BESS-SITE-01, so the node is attached to that site in market PX-DAM.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

SQL = """
INSERT INTO battery_master.price_node (market_id, node_code, name, node_type, site_id)
SELECT m.market_id, 'NODE-SITE01', 'Kolkata Grid Storage Site settlement node', 'POI', s.site_id
FROM battery_master.market m, battery_master.site s
WHERE m.market_code = 'PX-DAM' AND s.site_code = 'KOL-BESS-SITE-01'
ON CONFLICT (node_code) DO NOTHING;
"""


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(SQL)
            print(f"inserted {cur.rowcount} node(s)")
            cur.execute("""SELECT n.node_id, n.node_code, m.market_code, s.site_code
                           FROM battery_master.price_node n JOIN battery_master.market m USING (market_id)
                           LEFT JOIN battery_master.site s USING (site_id) ORDER BY n.node_id""")
            for row in cur.fetchall():
                print("  ", row)
        if commit:
            conn.commit()
            print("committed")
        else:
            conn.rollback()
            print("rolled back (rehearsal) - pass --commit to apply")
    finally:
        conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
