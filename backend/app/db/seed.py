from __future__ import annotations

from datetime import date, timedelta

from app.db.database import bool_to_int, get_connection, initialize_schema

DEMO_TODAY = date(2026, 6, 22)

CUSTOMERS = [
    ("cus_1001", "Avery Stone", "avery.stone@mailinator.com", "personal", "US", "2022-04-11", "gold", True, 7200.50, False, False, 0),
    ("cus_1002", "Mina Chen", "mina.chen@mailinator.com", "personal", "US", "2025-12-18", "standard", False, 220.00, False, False, 0),
    ("cus_1003", "Jon Bell", "jon.bell@mailinator.com", "personal", "US", "2024-08-02", "silver", False, 415.20, True, True, 0),
    ("cus_1004", "Priya Kapoor", "priya.kapoor@mailinator.com", "business", "US", "2020-03-23", "platinum", True, 9640.45, False, False, 0),
    ("cus_1005", "Leo Martins", "leo.martins@mailinator.com", "personal", "US", "2023-11-06", "standard", False, 310.10, False, False, 0),
    ("cus_1006", "Nora Ellis", "nora.ellis@mailinator.com", "personal", "US", "2021-01-14", "gold", False, 2890.00, False, False, 0),
    ("cus_1007", "Omar Wright", "omar.wright@mailinator.com", "business", "US", "2022-09-29", "silver", False, 720.55, False, False, 2),
    ("cus_1008", "Sara Ahmed", "sara.ahmed@mailinator.com", "personal", "US", "2026-01-09", "standard", False, 64.99, False, False, 0),
    ("cus_1009", "Ben Ortega", "ben.ortega@mailinator.com", "personal", "US", "2019-10-22", "platinum", True, 12400.30, False, False, 0),
    ("cus_1010", "Ivy Thompson", "ivy.thompson@mailinator.com", "personal", "US", "2024-06-17", "silver", False, 531.00, False, False, 0),
    ("cus_1011", "Rafael Souza", "rafael.souza@mailinator.com", "business", "US", "2025-03-05", "standard", False, 184.00, False, False, 0),
    ("cus_1012", "Grace Kim", "grace.kim@mailinator.com", "personal", "US", "2021-07-30", "gold", True, 2050.75, False, False, 0),
    ("cus_1013", "Elena Rossi", "elena.rossi@mailinator.com", "personal", "US", "2023-05-20", "standard", False, 335.80, False, False, 0),
    ("cus_1014", "Dylan Park", "dylan.park@mailinator.com", "personal", "US", "2026-02-01", "standard", False, 140.00, False, False, 0),
    ("cus_1015", "Chloe Nguyen", "chloe.nguyen@mailinator.com", "business", "US", "2018-12-12", "platinum", True, 15220.00, False, False, 0),
]

PRODUCTS = [
    ("prod_001", "APP-HOOD-01", "Everyday Hoodie", "apparel", "physical", False, False, False, False),
    ("prod_002", "HOME-LAMP-02", "Desk Lamp", "home", "physical", False, False, False, False),
    ("prod_003", "ELEC-HEAD-11", "Noise Canceling Headphones", "electronics", "physical", False, False, False, False),
    ("prod_004", "BAG-TOTE-07", "Italian Leather Tote", "accessories", "physical", False, False, False, False),
    ("prod_005", "SALE-SCARF-99", "Clearance Silk Scarf", "accessories", "physical", True, False, False, False),
    ("prod_006", "FIT-YOGA-02", "Yoga Mat", "fitness", "physical", False, False, False, False),
    ("prod_007", "KIT-KNIFE-04", "Chef Knife", "kitchen", "physical", False, False, False, False),
    ("prod_008", "DIG-COURSE-01", "Photography Masterclass", "digital", "digital", False, True, False, False),
    ("prod_009", "WATCH-AUTO-12", "Automatic Field Watch", "jewelry", "physical", False, False, False, False),
    ("prod_010", "BOOK-SET-03", "Design Books Set", "books", "physical", False, False, False, False),
    ("prod_011", "OUT-BACK-05", "Commuter Backpack", "outdoor", "physical", False, False, False, False),
    ("prod_012", "HOME-VASE-10", "Ceramic Vase", "home", "physical", False, False, False, False),
    ("prod_013", "BEAUTY-MASK-08", "Silk Sleep Mask", "beauty", "physical", False, False, False, True),
    ("prod_014", "SHOE-RUN-03", "Road Running Shoes", "footwear", "physical", False, False, False, False),
    ("prod_015", "TRVL-DUFF-06", "Weekender Duffel", "travel", "physical", False, False, False, False),
    ("prod_016", "SUB-COFFEE-01", "Coffee Club Subscription", "grocery", "subscription", False, False, True, False),
    ("prod_017", "ELEC-CAM-04", "Action Camera", "electronics", "physical", False, False, False, False),
    ("prod_018", "TOY-ROBOT-02", "Learning Robot", "toys", "physical", False, False, False, False),
    ("prod_019", "DIG-EBOOK-02", "Cookbook E-book", "digital", "digital", False, True, False, False),
    ("prod_020", "HOME-BLANK-09", "Weighted Blanket", "home", "physical", False, False, False, False),
    ("prod_021", "BEAUTY-SERUM-01", "Vitamin C Serum", "beauty", "physical", False, False, False, True),
    ("prod_022", "APP-JACKET-05", "Rain Jacket", "apparel", "physical", False, False, False, False),
    ("prod_023", "KIT-PAN-08", "Carbon Steel Pan", "kitchen", "physical", False, False, False, False),
    ("prod_024", "OUT-TENT-01", "Two Person Tent", "outdoor", "physical", False, False, False, False),
    ("prod_025", "SALE-WALLET-77", "Final Sale Wallet", "accessories", "physical", True, False, False, False),
]

PRIMARY_ORDERS = [
    ("ord_5001", "cus_1001", "2026-06-01", "2026-06-03", "2026-06-05", "2026-06-06", "delivered", "delivered", 129.99, "USD", "US", "prod_001", "opened", True, True),
    ("ord_5002", "cus_1002", "2026-04-20", "2026-04-22", "2026-04-25", "2026-04-27", "delivered", "delivered", 89.50, "USD", "US", "prod_002", "unopened", True, True),
    ("ord_5003", "cus_1003", "2026-06-07", "2026-06-09", "2026-06-12", "2026-06-13", "delivered", "delivered", 240.00, "USD", "US", "prod_003", "unopened", True, True),
    ("ord_5004", "cus_1004", "2026-05-04", "2026-05-06", "2026-05-10", "2026-05-11", "delivered", "delivered", 315.75, "USD", "US", "prod_004", "opened", True, True),
    ("ord_5005", "cus_1005", "2026-06-10", "2026-06-12", "2026-06-16", "2026-06-17", "delivered", "delivered", 49.99, "USD", "US", "prod_005", "unopened", True, True),
    ("ord_5006", "cus_1006", "2026-06-04", "2026-06-06", "2026-06-09", "2026-06-10", "delivered", "delivered", 76.00, "USD", "US", "prod_006", "unopened", True, True),
    ("ord_5007", "cus_1007", "2026-06-03", "2026-06-05", "2026-06-08", "2026-06-09", "delivered", "delivered", 115.00, "USD", "US", "prod_007", "unopened", True, True),
    ("ord_5008", "cus_1008", "2026-06-15", None, "2026-06-15", "2026-06-15", "delivered", "digital delivered", 64.99, "USD", "US", "prod_008", "digital_delivered", False, False),
    ("ord_5009", "cus_1009", "2026-06-01", "2026-06-03", "2026-06-06", "2026-06-07", "delivered", "delivered", 899.00, "USD", "US", "prod_009", "unopened", True, True),
    ("ord_5010", "cus_1010", "2026-06-02", "2026-06-04", None, "2026-06-10", "lost", "carrier marked lost", 142.35, "USD", "US", "prod_010", "unopened", True, True),
    ("ord_5011", "cus_1011", "2026-06-18", "2026-06-19", None, "2026-06-25", "shipped", "in transit", 184.00, "USD", "US", "prod_011", "unopened", True, True),
    ("ord_5012", "cus_1012", "2026-06-06", "2026-06-08", "2026-06-11", "2026-06-12", "delivered", "delivered with carrier damage note", 210.00, "USD", "US", "prod_012", "damaged", True, True),
    ("ord_5013", "cus_1013", "2026-06-12", "2026-06-14", "2026-06-17", "2026-06-18", "delivered", "delivered", 58.00, "USD", "US", "prod_013", "opened", True, True),
    ("ord_5014", "cus_1014", "2026-05-26", "2026-05-28", "2026-05-31", "2026-06-01", "delivered", "delivered", 140.00, "USD", "US", "prod_014", "used", True, True),
    ("ord_5015", "cus_1015", "2026-05-01", "2026-05-04", "2026-05-09", "2026-05-10", "delivered", "delivered", 199.00, "USD", "US", "prod_015", "unopened", True, True),
]


def _extra_orders() -> list[tuple]:
    orders = []
    product_ids = [product[0] for product in PRODUCTS]
    for index in range(25):
        customer = CUSTOMERS[index % len(CUSTOMERS)][0]
        product = product_ids[(index + 5) % len(product_ids)]
        order_number = 6001 + index
        purchase_date = DEMO_TODAY - timedelta(days=45 + index)
        delivered_date = purchase_date + timedelta(days=5)
        amount = round(35 + (index * 11.75), 2)
        orders.append(
            (
                f"ord_{order_number}",
                customer,
                purchase_date.isoformat(),
                (purchase_date + timedelta(days=2)).isoformat(),
                delivered_date.isoformat(),
                (purchase_date + timedelta(days=6)).isoformat(),
                "delivered",
                "delivered",
                amount,
                "USD",
                "US",
                product,
                "unopened",
                True,
                True,
            )
        )
    return orders


ORDERS = PRIMARY_ORDERS + _extra_orders()

RETURN_REQUESTS = [
    ("ret_7001", "cus_1001", "ord_5001", "2026-06-22", "Changed mind", "The hoodie is not the right size.", "refund", "Pending"),
    ("ret_7002", "cus_1002", "ord_5002", "2026-06-22", "Changed mind", "I never opened the lamp.", "refund", "Pending"),
    ("ret_7003", "cus_1003", "ord_5003", "2026-06-22", "Changed mind", "Please refund the headphones.", "refund", "Pending"),
    ("ret_7004", "cus_1004", "ord_5004", "2026-06-22", "VIP exception", "The tote is not what I expected.", "refund", "Pending"),
    ("ret_7005", "cus_1005", "ord_5005", "2026-06-22", "Final sale", "I want to return this scarf.", "refund", "Pending"),
    ("ret_7006", "cus_1006", "ord_5006", "2026-06-22", "Frequent refunds", "The mat is still sealed.", "refund", "Pending"),
    ("ret_7007", "cus_1007", "ord_5007", "2026-06-22", "Chargeback review", "The knife is unopened.", "refund", "Pending"),
    ("ret_7008", "cus_1008", "ord_5008", "2026-06-22", "Digital denial", "I do not want the course.", "refund", "Pending"),
    ("ret_7009", "cus_1009", "ord_5009", "2026-06-22", "High value order", "Please refund the watch.", "refund", "Pending"),
    ("ret_7010", "cus_1010", "ord_5010", "2026-06-22", "Lost shipment", "My package never arrived.", "replacement", "Pending"),
    ("ret_7011", "cus_1011", "ord_5011", "2026-06-22", "Undelivered", "It is still in transit.", "refund", "Pending"),
    ("ret_7012", "cus_1012", "ord_5012", "2026-06-22", "Damaged on arrival", "The vase arrived broken.", "refund", "Pending"),
    ("ret_7013", "cus_1013", "ord_5013", "2026-06-22", "Hygiene product", "The mask was opened.", "refund", "Pending"),
    ("ret_7014", "cus_1014", "ord_5014", "2026-06-22", "Used item", "The shoes were worn.", "refund", "Pending"),
    ("ret_7015", "cus_1015", "ord_5015", "2026-06-22", "VIP window", "I want to return the duffel.", "refund", "Pending"),
]

EVIDENCE = [
    ("ev_8001", "ret_7010", "tracking_document", "/demo/evidence/lost-shipment.pdf", True, "2026-06-22"),
    ("ev_8002", "ret_7012", "photo", "/demo/evidence/broken-vase.jpg", True, "2026-06-22"),
    ("ev_8003", "ret_7012", "damage_report", "/demo/evidence/carrier-damage.txt", True, "2026-06-22"),
    ("ev_8004", "ret_7013", "photo", "/demo/evidence/opened-mask.jpg", True, "2026-06-22"),
]


def _refund_history() -> list[tuple]:
    rows = []
    seeds = [
        ("cus_1001", "ord_6001", 44.0, "Size exchange", "2025-12-10"),
        ("cus_1002", "ord_6002", 32.5, "Late delivery", "2025-10-11"),
        ("cus_1004", "ord_6004", 120.0, "VIP goodwill", "2025-09-02"),
        ("cus_1004", "ord_6019", 88.0, "Wrong color", "2026-01-15"),
        ("cus_1006", "ord_6006", 51.0, "Changed mind", "2025-08-01"),
        ("cus_1006", "ord_6021", 67.0, "Damaged item", "2025-11-09"),
        ("cus_1006", "ord_6006", 74.0, "Wrong item", "2026-02-18"),
        ("cus_1006", "ord_6021", 39.0, "Late delivery", "2026-05-12"),
        ("cus_1007", "ord_6007", 29.0, "Defect", "2025-12-22"),
        ("cus_1009", "ord_6009", 180.0, "VIP exchange", "2025-07-13"),
        ("cus_1010", "ord_6010", 42.0, "Carrier delay", "2025-06-30"),
        ("cus_1012", "ord_6012", 75.0, "Damaged on arrival", "2025-12-05"),
        ("cus_1015", "ord_6015", 92.0, "VIP return", "2025-08-18"),
    ]
    while len(seeds) < 20:
        index = len(seeds)
        customer_id = CUSTOMERS[index % len(CUSTOMERS)][0]
        order_id = ORDERS[15 + index][0]
        seeds.append((customer_id, order_id, round(25 + index * 6.5, 2), "Historical refund", "2025-04-01"))
    for index, seed in enumerate(seeds[:20], start=1):
        rows.append((f"ref_{9000 + index}", *seed))
    return rows


REFUND_HISTORY = _refund_history()

FRAUD_ASSESSMENTS = [
    ("fraud_1001", "cus_1001", True, 0.05, False, False, False, "2026-06-01"),
    ("fraud_1002", "cus_1002", True, 0.10, False, False, False, "2026-06-01"),
    ("fraud_1003", "cus_1003", False, 0.82, True, True, True, "2026-06-20"),
    ("fraud_1004", "cus_1004", True, 0.04, False, False, False, "2026-06-01"),
    ("fraud_1005", "cus_1005", True, 0.15, False, False, False, "2026-06-01"),
    ("fraud_1006", "cus_1006", True, 0.22, False, False, False, "2026-06-01"),
    ("fraud_1007", "cus_1007", True, 0.65, False, False, True, "2026-06-20"),
    ("fraud_1008", "cus_1008", True, 0.08, False, False, False, "2026-06-01"),
    ("fraud_1009", "cus_1009", True, 0.12, False, False, False, "2026-06-01"),
    ("fraud_1010", "cus_1010", True, 0.18, False, False, False, "2026-06-01"),
    ("fraud_1011", "cus_1011", True, 0.20, False, False, False, "2026-06-01"),
    ("fraud_1012", "cus_1012", True, 0.07, False, False, False, "2026-06-01"),
    ("fraud_1013", "cus_1013", True, 0.13, False, False, False, "2026-06-01"),
    ("fraud_1014", "cus_1014", True, 0.09, False, False, False, "2026-06-01"),
    ("fraud_1015", "cus_1015", True, 0.03, False, False, False, "2026-06-01"),
]


def _migrate_legacy_email_domains(connection) -> None:
    connection.execute(
        """
        UPDATE Customer
        SET email = REPLACE(email, '@example.com', '@mailinator.com')
        WHERE lower(email) LIKE '%@example.com'
        """
    )


def seed_demo_data(reset: bool = False) -> None:
    initialize_schema()
    with get_connection() as connection:
        if reset:
            for table in (
                "AgentDecisionLog",
                "PolicyIndexMetadata",
                "PolicyChunk",
                "Evidence",
                "RefundHistory",
                "FraudAssessment",
                "ReturnRequest",
                "OrderItem",
                "Orders",
                "Product",
                "Customer",
            ):
                connection.execute(f"DELETE FROM {table}")

        connection.executemany(
            """
            INSERT OR IGNORE INTO Customer (
                customer_id, name, email, account_type, country, account_created_date,
                loyalty_tier, vip_status, lifetime_spend, fraud_flag,
                under_investigation, chargeback_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (*row[:7], bool_to_int(row[7]), row[8], bool_to_int(row[9]), bool_to_int(row[10]), row[11])
                for row in CUSTOMERS
            ],
        )

        connection.executemany(
            """
            INSERT OR IGNORE INTO Product (
                product_id, sku, name, category, product_type, final_sale,
                digital_download, subscription_product, hygiene_sensitive
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (*row[:5], bool_to_int(row[5]), bool_to_int(row[6]), bool_to_int(row[7]), bool_to_int(row[8]))
                for row in PRODUCTS
            ],
        )

        connection.executemany(
            """
            INSERT OR IGNORE INTO Orders (
                order_id, customer_id, purchase_date, shipment_date, delivered_date,
                expected_delivery_date, status, tracking_status, total_amount,
                currency, shipping_country
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [row[:11] for row in ORDERS],
        )

        connection.executemany(
            """
            INSERT OR IGNORE INTO OrderItem (
                order_item_id, order_id, product_id, quantity, unit_price, condition,
                serial_number_present, original_packaging_present, original_accessories_present
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    f"item_{order[0]}",
                    order[0],
                    order[11],
                    1,
                    order[8],
                    order[12],
                    bool_to_int(order[13]),
                    bool_to_int(order[14]),
                    bool_to_int(order[14]),
                )
                for order in ORDERS
            ],
        )

        connection.executemany(
            """
            INSERT OR IGNORE INTO ReturnRequest (
                request_id, customer_id, order_id, request_date, reason,
                customer_comment, requested_resolution, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            RETURN_REQUESTS,
        )

        connection.executemany(
            """
            INSERT OR IGNORE INTO Evidence (
                evidence_id, request_id, type, file_path, verified, uploaded_date
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [(row[0], row[1], row[2], row[3], bool_to_int(row[4]), row[5]) for row in EVIDENCE],
        )

        connection.executemany(
            """
            INSERT OR IGNORE INTO RefundHistory (
                refund_id, customer_id, order_id, refund_amount, refund_reason, approved_date
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            REFUND_HISTORY,
        )

        connection.executemany(
            """
            INSERT OR IGNORE INTO FraudAssessment (
                assessment_id, customer_id, identity_verified, payment_risk_score,
                ip_mismatch, multiple_account_match, manual_review_required, assessment_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (row[0], row[1], bool_to_int(row[2]), row[3], bool_to_int(row[4]), bool_to_int(row[5]), bool_to_int(row[6]), row[7])
                for row in FRAUD_ASSESSMENTS
            ],
        )

        _migrate_legacy_email_domains(connection)


def main() -> None:
    seed_demo_data(reset=True)
    print("Seeded SQLite refund agent demo database.")


if __name__ == "__main__":
    main()
