-- ALTERNATIVE CONFIGURATIONS: do not execute this entire file.
-- Each block is a separate design for a fresh database.
-- Use scripts/benchmark.py or copy one block only; index names repeat.

-- baseline


-- single_column
CREATE INDEX idx_customer ON orders(customer_id);
CREATE INDEX idx_region ON orders(region);
CREATE INDEX idx_status ON orders(status);

-- composite
CREATE INDEX idx_customer_history ON orders(customer_id, created_at DESC, id DESC);
CREATE INDEX idx_region_sales ON orders(region, status, created_at);
CREATE INDEX idx_queue ON orders(status, created_at, id);

-- covering
CREATE INDEX idx_customer_history ON orders(customer_id, created_at DESC, id DESC, status, amount_cents);
CREATE INDEX idx_region_sales ON orders(region, status, created_at, amount_cents);
CREATE INDEX idx_queue ON orders(status, created_at, id, customer_id, amount_cents);

-- partial
CREATE INDEX idx_customer_history ON orders(customer_id, created_at DESC, id DESC, status, amount_cents);
CREATE INDEX idx_region_sales ON orders(region, status, created_at, amount_cents);
CREATE INDEX idx_open_queue ON orders(created_at, id, customer_id, amount_cents) WHERE status = 'open';
