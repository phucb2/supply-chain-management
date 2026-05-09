import time

import httpx


def main() -> int:
    base = "http://localhost:8000"
    payload = {
        "external_order_id": f"E2E-{int(time.time())}",
        "source": "shopify",
        "customer_category": "b2c",
        "customer_name": "E2E User",
        "customer_email": "e2e@example.com",
        "shipping_address": "123 Test St",
        "req_delivery_date": "2026-05-20",
        "request_type": "b2c",
        "origin": "main_warehouse",
        "destination": "HCM",
        "items": [
            {
                "sku": "E2E-SKU-1",
                "product_name": "E2E Product",
                "quantity": 2,
                "unit_price": 10.5,
                "weight_per_unit_kg": 1.2,
            }
        ],
    }

    with httpx.Client(timeout=30) as client:
        health = client.get(f"{base}/health")
        print("health:", health.status_code, health.text)

        imported = client.post(f"{base}/orders/import", json=payload)
        print("import:", imported.status_code, imported.text)
        if imported.status_code != 201:
            return 1

        sale_order_id = imported.json()["sale_order_id"]
        current = client.get(f"{base}/orders/{sale_order_id}")
        print("get_order:", current.status_code, current.text)
        if current.status_code != 200:
            return 1

        deadline = time.time() + 45
        final_status = None
        while time.time() < deadline:
            polled = client.get(f"{base}/orders/{sale_order_id}")
            if polled.status_code != 200:
                print("poll_failed:", polled.status_code, polled.text)
                return 1
            final_status = polled.json().get("status")
            print("poll_status:", final_status)
            if final_status in {"in_transit", "delivered", "exception", "cancelled"}:
                break
            time.sleep(3)

        print("final_status:", final_status)
        if final_status not in {"in_transit", "delivered", "exception", "cancelled"}:
            print("E2E_TIMEOUT")
            return 1

    print("E2E_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
