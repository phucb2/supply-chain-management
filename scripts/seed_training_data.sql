DO $$
DECLARE
    carriers TEXT[] := ARRAY['FedEx','UPS','DHL','USPS'];
    channels TEXT[] := ARRAY['shopify','amazon','manual','batch-test'];
    i INT;
    oid UUID;
    sid UUID;
    ship_at TIMESTAMPTZ;
    deliver_at TIMESTAMPTZ;
    eta_hours DOUBLE PRECISION;
BEGIN
    FOR i IN 1..50 LOOP
        oid := uuid_generate_v4();
        sid := uuid_generate_v4();
        ship_at := now() - (random() * interval '30 days');
        eta_hours := 12 + random() * 120;
        deliver_at := ship_at + (eta_hours * interval '1 hour');

        INSERT INTO orders (id, external_order_id, channel, status, customer_name, shipping_address, created_at, updated_at)
        VALUES (oid, 'SYNTH-' || i || '-' || extract(epoch from now())::int, channels[1 + floor(random()*4)::int], 'delivered', 'Synth User ' || i, i || '00 Synth St', ship_at, deliver_at);

        INSERT INTO order_items (order_id, sku, product_name, quantity, unit_price)
        VALUES (oid, 'SKU-' || (1 + floor(random()*20)::int), 'Product ' || i, 1 + floor(random()*5)::int, 5 + random()*50);

        IF random() > 0.5 THEN
            INSERT INTO order_items (order_id, sku, product_name, quantity, unit_price)
            VALUES (oid, 'SKU-' || (21 + floor(random()*20)::int), 'Extra ' || i, 1 + floor(random()*3)::int, 3 + random()*30);
        END IF;

        INSERT INTO shipments (id, order_id, carrier, tracking_number, status, created_at, updated_at, delivered_at)
        VALUES (sid, oid, carriers[1 + floor(random()*4)::int], 'TRK-' || substr(md5(random()::text), 1, 10), 'delivered', ship_at, deliver_at, deliver_at);

        INSERT INTO shipment_packages (shipment_id, weight, dimensions, label_url)
        VALUES (sid, 0.5 + random()*25, '30x20x15', 'https://labels.example.com/TRK-' || i || '.pdf');
    END LOOP;
END $$;
