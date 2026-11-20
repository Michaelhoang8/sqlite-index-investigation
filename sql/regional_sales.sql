SELECT substr(created_at, 1, 10) AS order_day,
       COUNT(*) AS orders, SUM(amount_cents) AS revenue_cents
FROM orders
WHERE region = ? AND status = 'paid' AND created_at >= ?
GROUP BY substr(created_at, 1, 10)
ORDER BY order_day;
