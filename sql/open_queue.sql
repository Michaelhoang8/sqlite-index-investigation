SELECT id, created_at, customer_id, amount_cents
FROM orders
WHERE status = 'open' AND created_at >= ?
ORDER BY created_at, id
LIMIT 100;
