SELECT id, created_at, status, amount_cents
FROM orders
WHERE customer_id = ?
ORDER BY created_at DESC, id DESC
LIMIT 25;
