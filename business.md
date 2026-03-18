### **Business Requirements Summary**
These are the core business requirements of the Supply Chain Management System.

**Real-time tracking (Streaming Processing)**
R1: Allow drivers and warehouse workers to update tracking information in real time
R2: Allow customers to monitor their shipment tracking status

**Order processing (Streaming Processing)**
R3: The system must detect and reject duplicate order submissions to prevent double-processing
R4: Synchronize incoming orders from eCommerce and ERP systems (ERP will be mocked)

**Alerts & notifications (Streaming Processing)**
R5: Expose webhook/API endpoints to send alerts on shipment events (e.g., delays, delivery completion, exceptions)

**Warehouse operations (Near real time, low latency CRUD)**
R6: Allow warehouse workers to record goods-in and goods-out events
R7: Allow add/remove drivers or transportation vendors

**Reporting (Batch Processing)**
R8: Generate monthly/quarterly operational reports from historical data

**Machine learning (Batch Training + Streaming Inference)**
R9: Train ETA forecasting model on historical shipment data (batch)
R10: Serve real-time ETA predictions to customers (streaming)


### **Non-Functional Requirements**
The system is designed to be robust and accessible to ensure high operational efficiency:

*   **Multi-Platform Accessibility:** The solution must be accessible through both **Web and Mobile applications** to support office staff and drivers.
*   **Security and Governance:** Implementation of **Role-Based Access Control (RBAC)** and **user activity logging** is mandatory for traceability and regulatory compliance.
*   **Usability:** The interface must be **user-friendly and intuitive** to facilitate rapid adoption by warehouse and transportation staff.
*   **Reliability and Independence:** The architecture must avoid **vendor lock-in risks** and ensure **high availability** through an Active/Passive failover setup.

### **Technology Stack**
The project employs a modern distributed data architecture to handle both real-time events and historical analysis:

*   **Apache Kafka:** Serves as the central **event bus**, handling high-velocity data such as driver status updates and triggering automatic services like the ERP Goods Issue post. It is specifically chosen for its **high-throughput ingestion** and **event replay capabilities** for audits.
*   **PostgreSQL:** Functions as the **single source of truth (Operational DB)** for managing stateful data, such as vehicle requests, assignments, and historical records needed for monthly/quarterly reports.
*   **Kafka Streams:** Utilized for **streaming processing** to power real-time tracking features and machine learning inference for predictive analysis.
*   **REST API:** Acts as the gateway for **synchronizing orders** from eCommerce and ERP systems, receiving updates from the driver's mobile app, and exposing **webhook/API endpoints** for alert notifications.
*   **MinIO:** Employed as an **S3-compatible object store** for long-term **logging and backup**, ensuring data durability without vendor lock-in.
