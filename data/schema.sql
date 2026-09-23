-- WS4 Integration Sandbox — operational database ("System A")
--
-- Field-service work orders for a fleet of sites. Amounts are stored in CENTS,
-- which is the convention the operational team has always used.
--
-- NOTE FOR FACILITATORS (do not show learners): the seeded teaching defect is
-- in v_billing_export below. Answer key: docs/ANSWER-KEY.md

DROP VIEW IF EXISTS v_billing_export;
DROP TABLE IF EXISTS work_orders;

CREATE TABLE work_orders (
    id            INTEGER PRIMARY KEY,
    site_id       TEXT    NOT NULL,
    status        TEXT    NOT NULL CHECK (status IN ('completed', 'cancelled', 'scheduled')),
    scheduled_on  TEXT    NOT NULL,
    -- Monetary amounts are stored in CENTS throughout the operational system.
    amount_cents  INTEGER NOT NULL
);

CREATE INDEX idx_work_orders_status ON work_orders (status);

-- The billing export view, added years ago when finance asked for "the amounts".
--
-- It correctly filters to completed work only. But it exposes amount_cents
-- under the bare name "amount", with no conversion and no unit in the name.
-- Anything downstream that reads `amount` as a currency amount is off by 100x.
CREATE VIEW v_billing_export AS
    SELECT id           AS work_order_id,
           site_id      AS site_id,
           amount_cents AS amount          -- cents, exposed as "amount"
      FROM work_orders
     WHERE status = 'completed';
