# booking_sessions live schema


## `booking_sessions`


```sql
CREATE TABLE `booking_sessions` (
  `id` int NOT NULL AUTO_INCREMENT,
  `booking_code` varchar(20) NOT NULL,
  `machine_id` varchar(50) NOT NULL,
  `started_at` datetime NOT NULL,
  `completed_at` datetime DEFAULT NULL,
  `completed_stages` varchar(500) DEFAULT '',
  `last_stage` varchar(50) DEFAULT NULL,
  `resume_count` int DEFAULT '0',
  `status` enum('in_progress','completed','aborted','abandoned') DEFAULT 'in_progress',
  `abort_reason` varchar(255) DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_code_machine` (`booking_code`,`machine_id`),
  KEY `idx_code` (`booking_code`),
  KEY `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
```


### Sample rows (top 5)


*(no rows)*

