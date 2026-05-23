# Live Schema Snapshot — petgully_db

> Read-only introspection for Phase 1 contract design.

> Connection: spotless001@petgully-dbserver…/petgully_db (RDS Aurora MySQL)


**MySQL version:** `8.0.44`


**Total tables in DB:** 89


<details><summary>All table names</summary>


- `activity_expenses`
- `addon_credit_accounts`
- `addon_credit_transactions`
- `apartments`
- `bookings`
- `bot_menu_items`
- `categories_main`
- `chat_categories`
- `chat_settings`
- `chat_templates`
- `customer_credit_accounts`
- `customer_locations`
- `customers`
- `customersold`
- `driver_access_logs`
- `finance_import_runs`
- `finance_review_queue`
- `handbook_story_drafts`
- `handbook_story_pages`
- `handbook_user_stories`
- `marketing_posts`
- `medical_user_prefs`
- `mg_addons`
- `mg_booking_events`
- `mg_booking_groups`
- `mg_invoice_sequence`
- `mg_invoices`
- `mg_package_pricing`
- `mg_prime_credit_transactions`
- `mg_prime_memberships`
- `mg_slot_proposals`
- `mg_team_members`
- `mg_writeoffs`
- `mobile_grooming_bookings`
- `offline_contacts`
- `package_pricing`
- `pawgress_custom_completions`
- `pawgress_custom_tasks`
- `pawgress_med_doses`
- `pawgress_med_subscriptions`
- `pawgress_wallpaper`
- `payments`
- `pet_activities`
- `pet_breeds`
- `pet_health_facts`
- `pet_health_profile`
- `pet_health_profile_history`
- `pet_medical_access_log`
- `pet_medical_care_records`
- `pet_medical_files`
- `pet_medical_records`
- `pet_medical_report`
- `pet_medical_share_links`
- `pet_medical_tips_cache`
- `pet_medical_visit_medications`
- `pet_medical_visits`
- `pet_medical_weights`
- `pet_rag_chunks`
- `pet_rag_query_log`
- `pets`
- `pm_checklist`
- `pm_features`
- `pm_milestones`
- `pm_projects`
- `prime_credit_transactions`
- `prime_memberships`
- `prime_package_pricing`
- `route_plan_assignments`
- `route_plans`
- `rules`
- `salary_rules`
- `service_packages`
- `session_activities`
- `session_config`
- `session_events`
- `session_logs`
- `session_stages`
- `spotless_addons`
- `staff_active_sessions`
- `system_logs`
- `system_milestones`
- `transactions_canonical`
- `transactions_raw`
- `v_transactions_with_category`
- `van_staff_assignments`
- `vans`
- `waitlist`
- `zone_localities`
- `zones`


</details>

---


## `bookings`


```sql
CREATE TABLE `bookings` (
  `id` int NOT NULL AUTO_INCREMENT,
  `booking_code` varchar(20) NOT NULL,
  `customer_id` int NOT NULL,
  `pet_id` int NOT NULL,
  `session_type` varchar(50) DEFAULT 'small',
  `sval` int DEFAULT '120',
  `cval` int DEFAULT '120',
  `dval` int DEFAULT '60',
  `wval` int DEFAULT '60',
  `dryval` int DEFAULT '480',
  `fval` int DEFAULT '60',
  `wt` int DEFAULT '30',
  `ctype` int DEFAULT '100',
  `booking_date` date DEFAULT NULL,
  `booking_time` time DEFAULT NULL,
  `status` enum('pending','confirmed','completed','cancelled') DEFAULT 'pending',
  `payment_status` enum('pending','paid','refunded') DEFAULT 'pending',
  `amount` decimal(10,2) DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `cancel_reason` varchar(500) DEFAULT NULL,
  `cancelled_by` varchar(100) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `booking_code` (`booking_code`),
  KEY `idx_customer` (`customer_id`),
  KEY `idx_code` (`booking_code`),
  KEY `pet_id` (`pet_id`),
  CONSTRAINT `bookings_ibfk_1` FOREIGN KEY (`customer_id`) REFERENCES `customers` (`id`),
  CONSTRAINT `bookings_ibfk_2` FOREIGN KEY (`pet_id`) REFERENCES `pets` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=39 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
```


## `pets`


```sql
CREATE TABLE `pets` (
  `id` int NOT NULL AUTO_INCREMENT,
  `customer_id` int NOT NULL,
  `name` varchar(100) NOT NULL,
  `breed` varchar(100) DEFAULT NULL,
  `size` enum('small','medium','large','medium_large','xl') DEFAULT 'medium_large',
  `weight_kg` decimal(5,2) DEFAULT NULL,
  `age_years` int DEFAULT NULL,
  `photo_url` varchar(500) DEFAULT NULL,
  `notes` text,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_customer` (`customer_id`),
  CONSTRAINT `pets_ibfk_1` FOREIGN KEY (`customer_id`) REFERENCES `customers` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=631 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
```


## `customers`


```sql
CREATE TABLE `customers` (
  `id` int NOT NULL AUTO_INCREMENT,
  `email` varchar(255) NOT NULL,
  `password_hash` varchar(255) DEFAULT NULL,
  `name` varchar(100) DEFAULT NULL,
  `phone` varchar(20) DEFAULT NULL,
  `is_admin` tinyint(1) DEFAULT '0',
  `google_id` varchar(255) DEFAULT NULL,
  `profile_pic` varchar(500) DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `last_login` timestamp NULL DEFAULT NULL,
  `is_field_staff` tinyint(1) DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `email` (`email`),
  KEY `idx_email` (`email`)
) ENGINE=InnoDB AUTO_INCREMENT=3161 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
```


## `payments`


```sql
CREATE TABLE `payments` (
  `id` int NOT NULL AUTO_INCREMENT,
  `customer_id` int NOT NULL,
  `razorpay_order_id` varchar(100) DEFAULT NULL,
  `razorpay_payment_id` varchar(100) DEFAULT NULL,
  `razorpay_signature` varchar(255) DEFAULT NULL,
  `amount` decimal(10,2) NOT NULL,
  `currency` varchar(3) DEFAULT 'INR',
  `status` enum('created','authorized','captured','failed','refunded') DEFAULT 'created',
  `payment_type` enum('booking','prime_subscription','prime_upgrade','mobile_grooming','mg_prime_subscription','mobile_grooming_group') NOT NULL,
  `reference_id` varchar(100) DEFAULT NULL,
  `description` varchar(255) DEFAULT NULL,
  `method` varchar(50) DEFAULT NULL,
  `bank` varchar(100) DEFAULT NULL,
  `wallet` varchar(50) DEFAULT NULL,
  `vpa` varchar(100) DEFAULT NULL,
  `error_code` varchar(100) DEFAULT NULL,
  `error_description` text,
  `refund_id` varchar(100) DEFAULT NULL,
  `refund_amount` decimal(10,2) DEFAULT NULL,
  `notes` json DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `razorpay_order_id` (`razorpay_order_id`),
  KEY `idx_customer` (`customer_id`),
  KEY `idx_order` (`razorpay_order_id`),
  KEY `idx_payment` (`razorpay_payment_id`),
  KEY `idx_status` (`status`),
  KEY `idx_type` (`payment_type`),
  KEY `idx_ref` (`reference_id`),
  KEY `idx_created` (`created_at`)
) ENGINE=InnoDB AUTO_INCREMENT=519 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
```


## `service_packages`


```sql
CREATE TABLE `service_packages` (
  `id` int NOT NULL AUTO_INCREMENT,
  `code` varchar(50) NOT NULL,
  `name` varchar(100) NOT NULL,
  `description` text,
  `includes` text,
  `icon` varchar(10) DEFAULT 0xF09F9095,
  `display_order` int DEFAULT '0',
  `is_active` tinyint(1) DEFAULT '1',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `created_by` int DEFAULT NULL,
  `updated_by` int DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `code` (`code`),
  KEY `idx_code` (`code`),
  KEY `idx_active` (`is_active`),
  KEY `idx_display_order` (`display_order`)
) ENGINE=InnoDB AUTO_INCREMENT=6220 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
```


## `package_pricing`


```sql
CREATE TABLE `package_pricing` (
  `id` int NOT NULL AUTO_INCREMENT,
  `service_id` int NOT NULL,
  `size` enum('small','medium','large','xl') NOT NULL,
  `price` decimal(10,2) NOT NULL,
  `currency` varchar(3) DEFAULT 'INR',
  `is_active` tinyint(1) DEFAULT '1',
  `effective_from` date NOT NULL,
  `effective_to` date DEFAULT NULL,
  `notes` varchar(255) DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `created_by` int DEFAULT NULL,
  `updated_by` int DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_service_size_effective` (`service_id`,`size`,`effective_from`),
  KEY `idx_service` (`service_id`),
  KEY `idx_size` (`size`),
  KEY `idx_active` (`is_active`),
  KEY `idx_effective` (`effective_from`,`effective_to`)
) ENGINE=InnoDB AUTO_INCREMENT=119 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
```


## `mg_addons`


```sql
CREATE TABLE `mg_addons` (
  `id` int NOT NULL AUTO_INCREMENT,
  `addon_code` varchar(50) NOT NULL,
  `addon_name` varchar(100) NOT NULL,
  `price` decimal(10,2) NOT NULL,
  `icon` varchar(10) DEFAULT '➕',
  `description` text,
  `duration_minutes` int DEFAULT NULL,
  `applicable_packages` varchar(255) DEFAULT 'bath_pkg,trim_pkg,complete_pkg',
  `service_type` enum('both','spotless_only','mg_only') DEFAULT 'both',
  `display_order` int DEFAULT '0',
  `is_active` tinyint(1) DEFAULT '1',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `addon_code` (`addon_code`),
  KEY `idx_code` (`addon_code`),
  KEY `idx_active` (`is_active`)
) ENGINE=InnoDB AUTO_INCREMENT=8 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
```


## `session_config`


```sql
CREATE TABLE `session_config` (
  `id` int NOT NULL AUTO_INCREMENT,
  `mobile_number` varchar(15) NOT NULL,
  `customer_name` varchar(100) DEFAULT NULL,
  `session_type` varchar(50) NOT NULL DEFAULT 'small',
  `sval` int DEFAULT '120',
  `cval` int DEFAULT '120',
  `dval` int DEFAULT '60',
  `wval` int DEFAULT '60',
  `dryval` int DEFAULT '480',
  `fval` int DEFAULT '60',
  `wt` int DEFAULT '30',
  `stval` int DEFAULT '10',
  `msgval` int DEFAULT '10',
  `tdry` int DEFAULT '30',
  `pr` int DEFAULT '20',
  `ctype` int DEFAULT '100',
  `is_active` tinyint(1) DEFAULT '1',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `mobile_number` (`mobile_number`),
  KEY `idx_mobile` (`mobile_number`),
  KEY `idx_session_type` (`session_type`)
) ENGINE=InnoDB AUTO_INCREMENT=40 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
```


---

# Live data samples (LIMIT-bounded, read-only)


## bookings columns w/ recent rows

```sql
SELECT * FROM bookings ORDER BY created_at DESC LIMIT 3
```


| id | booking_code | customer_id | pet_id | session_type | sval | cval | dval | wval | dryval | fval | wt | ctype | booking_date | booking_time | status | payment_status | amount | created_at | updated_at | cancel_reason | cancelled_by |

|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

| 38 | PGD9F04A1C | 2201 | 143 | complete_pkg | 120 | 120 | 60 | 60 | 480 | 60 | 30 | 100 | ∅ | ∅ | confirmed | paid | 1380.00 | 2026-05-16 09:08:13 | 2026-05-16 09:08:13 | ∅ | ∅ |

| 37 | PG926DEC9E | 2498 | 225 | complete_pkg | 120 | 120 | 60 | 60 | 480 | 60 | 30 | 100 | ∅ | ∅ | confirmed | paid | 1800.00 | 2026-05-16 02:41:34 | 2026-05-16 02:41:34 | ∅ | ∅ |

| 36 | PGF1923200 | 3107 | 582 | bath_pkg | 120 | 120 | 60 | 60 | 480 | 60 | 30 | 100 | ∅ | ∅ | confirmed | paid | 999.00 | 2026-05-12 17:13:48 | 2026-05-12 17:13:48 | ∅ | ∅ |


## pets size distribution

```sql
SELECT size, COUNT(*) c FROM pets GROUP BY size
```


| size | c |

|---|---|

| medium | 1 |

| medium_large | 255 |

| small | 313 |

| xl | 25 |

|  | 16 |


## bookings session_type distribution

```sql
SELECT session_type, COUNT(*) c FROM bookings GROUP BY session_type ORDER BY c DESC
```


| session_type | c |

|---|---|

| bath_pkg | 8 |

| complete_pkg | 7 |

| trim_pkg | 1 |


## bookings status distribution

```sql
SELECT status, payment_status, COUNT(*) c FROM bookings GROUP BY status, payment_status
```


| status | payment_status | c |

|---|---|---|

| confirmed | paid | 16 |


## mg_addons spotless rows

```sql
SELECT addon_code, addon_name, price, service_type, applicable_packages, is_active FROM mg_addons WHERE service_type IN ('both','spotless_only')
```


| addon_code | addon_name | price | service_type | applicable_packages | is_active |

|---|---|---|---|---|---|

| dental_eyecare | Dental & Eyecare | 50.00 | both | bath_pkg,trim_pkg,complete_pkg,addon_only | 1 |

| paw_moisturizing | Paw Moisturizing | 50.00 | both | bath_pkg,trim_pkg,complete_pkg,addon_only | 1 |

| med_bath | Med Bath / Tick Bath | 100.00 | both | bath_pkg,complete_pkg | 1 |

| deshedding | De-shedding | 100.00 | both | bath_pkg,trim_pkg,complete_pkg,addon_only | 1 |

| dematting | De-Matting | 500.00 | both | bath_pkg,trim_pkg,complete_pkg,addon_only | 1 |

| hygiene_trim | Hygiene Trim | 300.00 | spotless_only | addon_only | 1 |


## service_packages all

```sql
SELECT * FROM service_packages
```


| id | code | name | description | includes | icon | display_order | is_active | created_at | updated_at | created_by | updated_by |

|---|---|---|---|---|---|---|---|---|---|---|---|

| 1 | diy_bath | DIY Bath | Self-service bath station | Bath | 🚿 | 1 | 1 | 2026-02-08 06:02:35 | 2026-02-08 06:02:35 | ∅ | ∅ |

| 4 | bath_pkg | Bath Package | Full bath service with ear cleaning and nail clipping | Bath,Ear Cleaning,Nail Clipping | 🛁 | 2 | 1 | 2026-02-08 06:02:36 | 2026-02-08 06:02:36 | ∅ | ∅ |

| 7 | trim_pkg | Trim Package | Hair trim with ear cleaning and nail clipping | Hair Trim,Ear Cleaning,Nail Clipping | ✂️ | 3 | 1 | 2026-02-08 06:02:36 | 2026-02-08 06:02:36 | ∅ | ∅ |

| 10 | complete_pkg | Complete Package | Complete grooming - bath, hair trim, ear cleaning and nail clipping | Bath,Hair Trim,Ear Cleaning,Nail Clipping | ✨ | 4 | 1 | 2026-02-08 06:02:36 | 2026-02-08 06:02:36 | ∅ | ∅ |


## package_pricing all

```sql
SELECT * FROM package_pricing
```


| id | service_id | size | price | currency | is_active | effective_from | effective_to | notes | created_at | updated_at | created_by | updated_by |

|---|---|---|---|---|---|---|---|---|---|---|---|---|

| 1 | 1 | small | 500.00 | INR | 1 | 2020-01-01 | ∅ | ∅ | 2026-02-08 06:02:38 | 2026-02-08 06:02:38 | ∅ | ∅ |

| 4 | 1 | medium | 500.00 | INR | 1 | 2020-01-01 | ∅ | ∅ | 2026-02-08 06:02:38 | 2026-02-21 06:22:52 | ∅ | ∅ |

| 5 | 1 | large | 500.00 | INR | 1 | 2020-01-01 | ∅ | ∅ | 2026-02-08 06:02:38 | 2026-02-21 06:22:52 | ∅ | ∅ |

| 6 | 1 | xl | 500.00 | INR | 1 | 2020-01-01 | ∅ | ∅ | 2026-02-08 06:02:39 | 2026-02-21 06:22:52 | ∅ | ∅ |

| 7 | 4 | small | 999.00 | INR | 1 | 2020-01-01 | ∅ | ∅ | 2026-02-08 06:02:39 | 2026-02-21 06:19:30 | ∅ | ∅ |

| 8 | 4 | medium | 1050.00 | INR | 1 | 2020-01-01 | ∅ | ∅ | 2026-02-08 06:02:39 | 2026-02-21 06:19:31 | ∅ | ∅ |

| 9 | 4 | large | 1050.00 | INR | 1 | 2020-01-01 | ∅ | ∅ | 2026-02-08 06:02:39 | 2026-02-21 06:19:31 | ∅ | ∅ |

| 10 | 4 | xl | 1200.00 | INR | 1 | 2020-01-01 | ∅ | ∅ | 2026-02-08 06:02:39 | 2026-02-21 06:19:31 | ∅ | ∅ |

| 11 | 7 | small | 1000.00 | INR | 1 | 2020-01-01 | ∅ | ∅ | 2026-02-08 06:02:40 | 2026-02-21 06:19:31 | ∅ | ∅ |

| 12 | 7 | medium | 1200.00 | INR | 1 | 2020-01-01 | ∅ | ∅ | 2026-02-08 06:02:40 | 2026-02-21 06:19:31 | ∅ | ∅ |

| 13 | 7 | large | 1200.00 | INR | 1 | 2020-01-01 | ∅ | ∅ | 2026-02-08 06:02:40 | 2026-02-21 06:19:32 | ∅ | ∅ |

| 14 | 7 | xl | 1400.00 | INR | 1 | 2020-01-01 | ∅ | ∅ | 2026-02-08 06:02:40 | 2026-02-21 06:19:32 | ∅ | ∅ |

| 15 | 10 | small | 1800.00 | INR | 1 | 2020-01-01 | ∅ | ∅ | 2026-02-08 06:02:41 | 2026-02-21 06:19:32 | ∅ | ∅ |

| 16 | 10 | medium | 2000.00 | INR | 1 | 2020-01-01 | ∅ | ∅ | 2026-02-08 06:02:41 | 2026-02-21 06:19:32 | ∅ | ∅ |

| 17 | 10 | large | 2000.00 | INR | 1 | 2020-01-01 | ∅ | ∅ | 2026-02-08 06:02:41 | 2026-02-21 06:19:33 | ∅ | ∅ |

| 18 | 10 | xl | 2400.00 | INR | 1 | 2020-01-01 | ∅ | ∅ | 2026-02-08 06:02:41 | 2026-03-01 15:18:03 | ∅ | ∅ |


## session_config sample

```sql
SELECT * FROM session_config ORDER BY 1 DESC LIMIT 3
```


| id | mobile_number | customer_name | session_type | sval | cval | dval | wval | dryval | fval | wt | stval | msgval | tdry | pr | ctype | is_active | created_at | updated_at |

|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

| 39 | PGD9F04A1C | Milo | complete_pkg | 120 | 120 | 60 | 60 | 480 | 60 | 30 | 10 | 10 | 30 | 20 | 100 | 1 | 2026-05-16 09:08:13 | 2026-05-16 09:08:13 |

| 38 | PG926DEC9E | Niko | complete_pkg | 120 | 120 | 60 | 60 | 480 | 60 | 30 | 10 | 10 | 30 | 20 | 100 | 1 | 2026-05-16 02:41:34 | 2026-05-16 02:41:34 |

| 37 | PGF1923200 | Oreo | bath_pkg | 120 | 120 | 60 | 60 | 480 | 60 | 30 | 10 | 10 | 30 | 20 | 100 | 1 | 2026-05-12 17:13:48 | 2026-05-12 17:13:48 |
