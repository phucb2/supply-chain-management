DO $$
DECLARE
    channels TEXT[] := ARRAY['shopify','amazon','manual','batch-test'];
    request_types TEXT[] := ARRAY['b2b','b2c'];
    i INT;
    customer_uuid UUID;
    request_uuid UUID;
    delivery_uuid UUID;
    order_uuid UUID;
    product_uuid UUID;
    ship_at TIMESTAMPTZ;
    deliver_at TIMESTAMPTZ;
    eta_hours DOUBLE PRECISION;
    selected_type shipment_request_type;
BEGIN
    INSERT INTO warehouses (warehouse_id, warehouse_name, location)
    VALUES (uuid_generate_v4(), 'Main Warehouse', 'HCM')
    ON CONFLICT DO NOTHING;

    INSERT INTO vendors (vendor_id, vendor_name, phone, tax_no, address)
    VALUES (uuid_generate_v4(), 'Seed Vendor', '000', 'SEED-TAX-001', 'HCM')
    ON CONFLICT (tax_no) DO NOTHING;

    FOR i IN 1..50 LOOP
        customer_uuid := uuid_generate_v4();
        request_uuid := uuid_generate_v4();
        delivery_uuid := uuid_generate_v4();
        order_uuid := uuid_generate_v4();
        product_uuid := uuid_generate_v4();
        ship_at := now() - (random() * interval '30 days');
        eta_hours := 12 + random() * 120;
        deliver_at := ship_at + (eta_hours * interval '1 hour');
        selected_type := request_types[1 + floor(random()*2)::int]::shipment_request_type;

        INSERT INTO customers (customer_id, customer_category, email, phone, address, city_province, created_at, updated_at)
        VALUES (
            customer_uuid,
            CASE WHEN selected_type = 'b2b' THEN 'b2b'::customer_type ELSE 'b2c'::customer_type END,
            'synth'||i||'@example.com',
            '0900'||to_char(i, 'FM0000'),
            i || '00 Synth St',
            'HCM',
            ship_at,
            deliver_at
        );

        IF selected_type = 'b2b' THEN
            INSERT INTO companies (customer_id, company_name, tax_id)
            VALUES (customer_uuid, 'Company ' || i, 'COMP-TAX-' || i);
        ELSE
            INSERT INTO individuals (customer_id, full_name, ssi)
            VALUES (customer_uuid, 'Synth User ' || i, 'SSI-' || i);
        END IF;

        INSERT INTO shipment_requests (request_id, request_type, request_date, origin, destination, planned_date, created_at)
        VALUES (request_uuid, selected_type, ship_at::date, 'Main Warehouse', 'District '||((i % 24)+1), deliver_at::date, ship_at);

        INSERT INTO delivery_orders (delivery_order_id, warehouse_id, request_id, delivery_date, status, created_at)
        VALUES (
            delivery_uuid,
            (SELECT warehouse_id FROM warehouses LIMIT 1),
            request_uuid,
            deliver_at::date,
            'delivered',
            ship_at
        );

        INSERT INTO sale_orders (
            sale_order_id, external_order_id, customer_id, delivery_order_id, source,
            order_date, req_delivery_date, status, total_amount, created_at, updated_at
        )
        VALUES (
            order_uuid,
            'SYNTH-' || i || '-' || extract(epoch from now())::int,
            customer_uuid,
            delivery_uuid,
            channels[1 + floor(random()*4)::int],
            ship_at::date,
            (ship_at + interval '2 days')::date,
            'delivered',
            100 + random()*200,
            ship_at,
            deliver_at
        );

        INSERT INTO products (product_id, sku, product_name, category, weight_per_unit_kg, created_at)
        VALUES (product_uuid, 'SKU-' || i, 'Product ' || i, 'general', 0.5 + random()*10, ship_at)
        ON CONFLICT (sku) DO NOTHING;

        INSERT INTO order_items (sale_order_id, product_id, quantity, unit_price, weight_per_unit_kg, total_kg)
        VALUES (
            order_uuid,
            (SELECT product_id FROM products WHERE sku = 'SKU-' || i),
            1 + floor(random()*5)::int,
            5 + random()*50,
            (SELECT weight_per_unit_kg FROM products WHERE sku = 'SKU-' || i),
            (1 + floor(random()*5)::int) * (SELECT weight_per_unit_kg FROM products WHERE sku = 'SKU-' || i)
        );

        INSERT INTO sale_order_status (sale_order_id, status, status_timestamp, remarks)
        VALUES
            (order_uuid, 'pending', ship_at, 'seed-created'),
            (order_uuid, 'in_transit', ship_at + interval '6 hour', 'seed-dispatched'),
            (order_uuid, 'delivered', deliver_at, 'seed-delivered');
    END LOOP;
END $$;
