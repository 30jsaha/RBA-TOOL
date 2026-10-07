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
-- Table structure for table `fraud_business_decision_jobs`
--

CREATE TABLE `fraud_business_decision_jobs` (
  `job_id` bigint(20) NOT NULL,
  `tin` char(9) NOT NULL,
  `requested_action` varchar(16) NOT NULL,
  `status` varchar(16) NOT NULL,
  `active_job_key` varchar(64) GENERATED ALWAYS AS (case when `status` in ('QUEUED','RUNNING','RETRYING','PAUSED') then concat(`tin`,':ACTIVE') else NULL end) STORED,
  `current_tax_type` varchar(3) DEFAULT NULL,
  `last_processed_source_id` bigint(20) DEFAULT NULL,
  `records_processed` bigint(20) NOT NULL DEFAULT 0,
  `records_overridden` bigint(20) NOT NULL DEFAULT 0,
  `records_skipped` bigint(20) NOT NULL DEFAULT 0,
  `records_failed` bigint(20) NOT NULL DEFAULT 0,
  `retry_count` int(11) NOT NULL DEFAULT 0,
  `error_message` longtext DEFAULT NULL,
  `started_at` datetime(6) DEFAULT NULL,
  `completed_at` datetime(6) DEFAULT NULL,
  `created_at` datetime(6) NOT NULL DEFAULT current_timestamp(6),
  `updated_at` datetime(6) NOT NULL DEFAULT current_timestamp(6),
  `requested_by_user_id` bigint(20) NOT NULL,
  `requested_status_before` tinyint(1) NOT NULL,
  `requested_status_after` tinyint(1) NOT NULL,
  `policy_version` varchar(32) NOT NULL,
  `worker_id` varchar(128) DEFAULT NULL,
  `lease_until` datetime(6) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Indexes for dumped tables
--

--
-- Indexes for table `fraud_business_decision_jobs`
--
ALTER TABLE `fraud_business_decision_jobs`
  ADD PRIMARY KEY (`job_id`),
  ADD UNIQUE KEY `uq_fbdj_active_tin` (`active_job_key`),
  ADD KEY `ix_fbdj_tin_status` (`tin`,`status`),
  ADD KEY `ix_fbdj_status_updated` (`status`,`updated_at`),
  ADD KEY `ix_fbdj_lease` (`status`,`lease_until`);

--
-- AUTO_INCREMENT for dumped tables
--

--
-- AUTO_INCREMENT for table `fraud_business_decision_jobs`
--
ALTER TABLE `fraud_business_decision_jobs`
  MODIFY `job_id` bigint(20) NOT NULL AUTO_INCREMENT;
COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
