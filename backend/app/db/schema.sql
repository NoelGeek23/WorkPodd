PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS Customer (
    customer_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    account_type TEXT,
    country TEXT,
    account_created_date DATE,
    loyalty_tier TEXT,
    vip_status BOOLEAN,
    lifetime_spend REAL,
    fraud_flag BOOLEAN,
    under_investigation BOOLEAN,
    chargeback_count INTEGER
);

CREATE TABLE IF NOT EXISTS Product (
    product_id TEXT PRIMARY KEY,
    sku TEXT UNIQUE,
    name TEXT,
    category TEXT,
    product_type TEXT,
    final_sale BOOLEAN,
    digital_download BOOLEAN,
    subscription_product BOOLEAN,
    hygiene_sensitive BOOLEAN
);

CREATE TABLE IF NOT EXISTS Orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT,
    purchase_date DATE,
    shipment_date DATE,
    delivered_date DATE,
    expected_delivery_date DATE,
    status TEXT,
    tracking_status TEXT,
    total_amount REAL,
    currency TEXT,
    shipping_country TEXT,
    FOREIGN KEY(customer_id)
        REFERENCES Customer(customer_id)
);

CREATE TABLE IF NOT EXISTS OrderItem (
    order_item_id TEXT PRIMARY KEY,
    order_id TEXT,
    product_id TEXT,
    quantity INTEGER,
    unit_price REAL,
    condition TEXT,
    serial_number_present BOOLEAN,
    original_packaging_present BOOLEAN,
    original_accessories_present BOOLEAN,
    FOREIGN KEY(order_id)
        REFERENCES Orders(order_id),
    FOREIGN KEY(product_id)
        REFERENCES Product(product_id)
);

CREATE TABLE IF NOT EXISTS ReturnRequest (
    request_id TEXT PRIMARY KEY,
    customer_id TEXT,
    order_id TEXT,
    request_date DATE,
    reason TEXT,
    customer_comment TEXT,
    requested_resolution TEXT,
    status TEXT CHECK(status IN (
        'Pending',
        'Approved',
        'Denied',
        'Manual Review',
        'Manager Review',
        'Closed'
    )),
    FOREIGN KEY(customer_id)
        REFERENCES Customer(customer_id),
    FOREIGN KEY(order_id)
        REFERENCES Orders(order_id)
);

CREATE TABLE IF NOT EXISTS Evidence (
    evidence_id TEXT PRIMARY KEY,
    request_id TEXT,
    type TEXT CHECK(type IN (
        'photo',
        'video',
        'receipt',
        'tracking_document',
        'damage_report'
    )),
    file_path TEXT,
    verified BOOLEAN,
    uploaded_date DATE,
    FOREIGN KEY(request_id)
        REFERENCES ReturnRequest(request_id)
);

CREATE TABLE IF NOT EXISTS RefundHistory (
    refund_id TEXT PRIMARY KEY,
    customer_id TEXT,
    order_id TEXT,
    refund_amount REAL,
    refund_reason TEXT,
    approved_date DATE,
    FOREIGN KEY(customer_id)
        REFERENCES Customer(customer_id),
    FOREIGN KEY(order_id)
        REFERENCES Orders(order_id)
);

CREATE TABLE IF NOT EXISTS FraudAssessment (
    assessment_id TEXT PRIMARY KEY,
    customer_id TEXT,
    identity_verified BOOLEAN,
    payment_risk_score REAL,
    ip_mismatch BOOLEAN,
    multiple_account_match BOOLEAN,
    manual_review_required BOOLEAN,
    assessment_date DATE,
    FOREIGN KEY(customer_id)
        REFERENCES Customer(customer_id)
);

CREATE TABLE IF NOT EXISTS AgentDecisionLog (
    decision_id TEXT PRIMARY KEY,
    request_id TEXT,
    decision TEXT,
    confidence_score REAL,
    reasoning TEXT,
    policy_sections_used TEXT,
    created_at DATETIME,
    FOREIGN KEY(request_id)
        REFERENCES ReturnRequest(request_id)
);

CREATE TABLE IF NOT EXISTS PolicyChunk (
    chunk_id TEXT PRIMARY KEY,
    section_title TEXT,
    content TEXT NOT NULL,
    embedding_json TEXT NOT NULL,
    updated_at DATETIME
);

CREATE TABLE IF NOT EXISTS PolicyIndexMetadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_orders_customer_id ON Orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_order_item_order_id ON OrderItem(order_id);
CREATE INDEX IF NOT EXISTS idx_return_request_customer_id ON ReturnRequest(customer_id);
CREATE INDEX IF NOT EXISTS idx_refund_history_customer_id ON RefundHistory(customer_id);
CREATE INDEX IF NOT EXISTS idx_fraud_assessment_customer_id ON FraudAssessment(customer_id);
CREATE INDEX IF NOT EXISTS idx_agent_decision_request_id ON AgentDecisionLog(request_id);
