-- phpMyAdmin SQL Dump
-- version 5.2.1
-- https://www.phpmyadmin.net/
--
-- Host: 127.0.0.1
-- Generation Time: Oct 06, 2026 at 06:53 AM
-- Server version: 10.4.32-MariaDB
-- PHP Version: 8.2.12

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";


/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;

--
-- Database: `rba_tool_database`
--

-- --------------------------------------------------------

--
-- Table structure for table `fraud_business_decisions`
--

CREATE TABLE `fraud_business_decisions` (
  `id` bigint(20) NOT NULL,
  `tax_type` varchar(3) NOT NULL,
  `source_table` varchar(64) NOT NULL,
  `source_record_id` bigint(20) NOT NULL,
  `source_identity_key` varchar(80) GENERATED ALWAYS AS (concat(`tax_type`,':',`source_record_id`)) STORED,
  `decision_version` int(10) UNSIGNED NOT NULL,
  `is_current` tinyint(1) NOT NULL DEFAULT 1,
  `current_identity_key` varchar(80) GENERATED ALWAYS AS (case when `is_current` = 1 then concat(`tax_type`,':',`source_record_id`) else NULL end) STORED,
  `previous_decision_id` bigint(20) DEFAULT NULL,
  `tin_original` varchar(64) DEFAULT NULL,
  `tin_key` char(9) DEFAULT NULL,
  `taxpayer_name_at_decision` varchar(255) DEFAULT NULL,
  `tax_period_year` smallint(5) UNSIGNED NOT NULL,
  `tax_period_month` tinyint(3) UNSIGNED DEFAULT NULL,
  `assessment_number` varchar(128) DEFAULT NULL,
  `tax_account_number` varchar(128) DEFAULT NULL,
  `upload_batch_id` varchar(128) DEFAULT NULL,
  `run_id` varchar(40) DEFAULT NULL,
  `source_user_id` bigint(20) DEFAULT NULL,
  `original_ml_result` varchar(32) NOT NULL,
  `original_rule_result` varchar(32) DEFAULT NULL,
  `original_predicted_fraud` varchar(32) DEFAULT NULL,
  `original_is_fraud` bigint(20) DEFAULT NULL,
  `original_is_fraud_rule` bigint(20) DEFAULT NULL,
  `original_rules_violated` longtext DEFAULT NULL,
  `original_fraud_probability` decimal(12,10) DEFAULT NULL,
  `original_explanation` longtext DEFAULT NULL,
  `original_justification` longtext DEFAULT NULL,
  `original_rule_evidence_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`original_rule_evidence_json`)),
  `original_source_metadata_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`original_source_metadata_json`)),
  `invalid_tin_state_at_decision` varchar(24) NOT NULL,
  `invalid_tin_id` bigint(20) DEFAULT NULL,
  `invalid_tin_status_at_decision` tinyint(1) DEFAULT NULL,
  `current_business_result` varchar(32) NOT NULL,
  `business_decision_type` varchar(32) NOT NULL,
  `decision_reason` varchar(64) NOT NULL,
  `override_reason` longtext DEFAULT NULL,
  `override_by_user_id` bigint(20) DEFAULT NULL,
  `decided_by_user_id` bigint(20) DEFAULT NULL,
  `decided_at` datetime(6) NOT NULL,
  `created_at` datetime(6) NOT NULL DEFAULT current_timestamp(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Indexes for dumped tables
--

--
-- Indexes for table `fraud_business_decisions`
--
ALTER TABLE `fraud_business_decisions`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `uq_fbd_source_version` (`tax_type`,`source_record_id`,`decision_version`),
  ADD UNIQUE KEY `uq_fbd_current_source` (`current_identity_key`),
  ADD KEY `ix_fbd_tin` (`tin_key`,`tax_type`,`tax_period_year`,`tax_period_month`),
  ADD KEY `ix_fbd_source_history` (`tax_type`,`source_record_id`,`decision_version`),
  ADD KEY `ix_fbd_period` (`tax_type`,`tax_period_year`,`tax_period_month`,`is_current`),
  ADD KEY `ix_fbd_batch_run` (`upload_batch_id`,`run_id`,`tax_type`),
  ADD KEY `ix_fbd_current_result` (`tax_type`,`current_business_result`,`is_current`),
  ADD KEY `ix_fbd_invalid_tin` (`tin_key`,`invalid_tin_state_at_decision`,`is_current`);

--
-- AUTO_INCREMENT for dumped tables
--

--
-- AUTO_INCREMENT for table `fraud_business_decisions`
--
ALTER TABLE `fraud_business_decisions`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;
COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
