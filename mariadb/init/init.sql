-- ==============================================================================
-- INIZIALIZZAZIONE AMBIENTE
-- ==============================================================================
DROP DATABASE IF EXISTS flowmate_db;
CREATE DATABASE flowmate_db;
USE flowmate_db;

-- ==============================================================================
-- TABELLE UTENTE E PREFERENZE
-- ==============================================================================
CREATE TABLE users (
    user_id CHAR(36) PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    weight_kg DECIMAL(5,2) NOT NULL,
    daily_kcal_goal INT NOT NULL,
    daily_steps_goal INT NOT NULL,
    registration_date DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE hobbies_catalog (
    hobby_id INT AUTO_INCREMENT PRIMARY KEY,
    hobby_name VARCHAR(100) UNIQUE NOT NULL,
    met_value DECIMAL(4,2) NOT NULL 
);

INSERT INTO hobbies_catalog (hobby_name, met_value) VALUES
('Light Walking', 3.0), ('Basketball', 8.0), ('Running', 9.8),
('Gaming', 1.5), ('Reading', 1.3), ('Yoga', 3.0),
('Meditation', 1.0), ('Stretching', 2.5), ('Cleaning', 3.5), ('Cooking', 2.0);

CREATE TABLE user_hobbies (
    user_id CHAR(36) NOT NULL,
    hobby_id INT NOT NULL,
    preference_level INT CHECK (preference_level BETWEEN 1 AND 5),
    PRIMARY KEY (user_id, hobby_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (hobby_id) REFERENCES hobbies_catalog(hobby_id) ON DELETE CASCADE
);

-- ==============================================================================
-- TABELLE BEACONS E PRESENZA (Allineate ai router)
-- ==============================================================================
-- ==============================================================================
-- TABELLE BEACONS E PRESENZA
-- ==============================================================================
CREATE TABLE beacons_catalog (
    beacon_id CHAR(36) PRIMARY KEY DEFAULT UUID(),
    user_id CHAR(36) NOT NULL,
    hardware_uuid VARCHAR(36) NOT NULL,
    major_id INT NOT NULL,
    minor_id INT NOT NULL,
    zone_name VARCHAR(100) NOT NULL,
    associated_hobby_id INT DEFAULT NULL,
    allow_notifications BOOLEAN DEFAULT TRUE,
    zone_icon VARCHAR(50) DEFAULT 'Place',
    weekday_from_time TIME DEFAULT '08:00:00',
    weekday_to_time TIME DEFAULT '22:00:00',
    weekend_from_time TIME DEFAULT '09:00:00',
    weekend_to_time TIME DEFAULT '23:00:00',
    inactivity_timeout_minutes INT DEFAULT NULL, -- NUOVO CAMPO (NULL = disabilitato)
    last_seen DATETIME DEFAULT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (associated_hobby_id) REFERENCES hobbies_catalog(hobby_id) ON DELETE SET NULL
);

CREATE TABLE zone_presence_logs (
    presence_id CHAR(36) PRIMARY KEY DEFAULT UUID(),
    user_id CHAR(36) NOT NULL,
    beacon_id CHAR(36) NOT NULL,
    entry_timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    exit_timestamp DATETIME DEFAULT NULL,
    duration_minutes INT DEFAULT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (beacon_id) REFERENCES beacons_catalog(beacon_id) ON DELETE CASCADE
);

-- ==============================================================================
-- TABELLE BIOMETRICHE E SCHEDULAZIONE
-- ==============================================================================
CREATE TABLE biometric_logs (
    log_id CHAR(36) PRIMARY KEY DEFAULT UUID(),
    user_id CHAR(36) NOT NULL,
    record_date DATE NOT NULL,
    steps_recorded INT DEFAULT 0,
    active_minutes INT DEFAULT 0,
    kcal_burned INT DEFAULT 0,
    UNIQUE KEY unique_user_date (user_id, record_date),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE silent_schedule (
    event_id CHAR(36) PRIMARY KEY DEFAULT UUID(),
    user_id CHAR(36) NOT NULL,
    day_of_week INT NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    event_type VARCHAR(50) DEFAULT 'Busy',
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- ==============================================================================
-- TABELLA SUGGERIMENTI (Estesa per Milestone 3)
-- ==============================================================================
CREATE TABLE activity_suggestions (
    suggestion_id CHAR(36) PRIMARY KEY DEFAULT UUID(),
    user_id CHAR(36) NOT NULL,
    hobby_id INT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    status ENUM('PROPOSED', 'ACCEPTED', 'REJECTED', 'COMPLETED') DEFAULT 'PROPOSED',
    suggested_duration_minutes INT DEFAULT 30,
    expected_kcal INT DEFAULT 150,
    baseline_active_minutes INT DEFAULT 0,
    completed_at DATETIME DEFAULT NULL,
    rejection_reason VARCHAR(50) DEFAULT NULL, 
    rejected_at DATETIME DEFAULT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (hobby_id) REFERENCES hobbies_catalog(hobby_id) ON DELETE CASCADE
);

CREATE TABLE chat_history (
    message_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id CHAR(36) NOT NULL,
    sender_role ENUM('user', 'assistant') NOT NULL,
    message_content TEXT NOT NULL,
    message_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- Tabella di supporto per lo storico notifiche (richiesta da presence.py)
CREATE TABLE sent_notifications (
    notification_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id CHAR(36) NOT NULL,
    beacon_id CHAR(36) NOT NULL,
    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (beacon_id) REFERENCES beacons_catalog(beacon_id) ON DELETE CASCADE
);

-- ==============================================================================
-- STORED PROCEDURE: MACCHINA A STATI (FSM) — FIX G + UPGRADE M4
-- ==============================================================================
DROP PROCEDURE IF EXISTS EvaluateProactiveState;
DELIMITER //
CREATE PROCEDURE EvaluateProactiveState(
    IN p_user_id CHAR(36),
    IN p_beacon_id CHAR(36),
    OUT p_state VARCHAR(50)
)
proc_exit: BEGIN
    DECLARE var_current_time TIME;
    DECLARE var_current_day INT;
    DECLARE var_busy_count INT;
    DECLARE var_opt_out_count INT;
    DECLARE var_recent_suggestion_count INT;
    DECLARE var_allow_notif BOOLEAN;

    SET var_current_time = CURRENT_TIME();
    SET var_current_day = WEEKDAY(CURRENT_DATE());

    -- 1. OPT-OUT odierno
    SELECT COUNT(*) INTO var_opt_out_count FROM activity_suggestions
    WHERE user_id = p_user_id AND status = 'REJECTED'
      AND rejection_reason = 'today_no' AND DATE(created_at) = CURDATE();
    IF var_opt_out_count > 0 THEN SET p_state = 'SILENT_USER_OPTED_OUT'; LEAVE proc_exit; END IF;

    -- 2. FASCIA BUSY
    SELECT COUNT(*) INTO var_busy_count FROM silent_schedule
    WHERE user_id = p_user_id AND day_of_week = var_current_day
      AND event_type = 'Busy' AND var_current_time BETWEEN start_time AND end_time;
    IF var_busy_count > 0 THEN SET p_state = 'SILENT_BUSY_SCHEDULE'; LEAVE proc_exit; END IF;

    -- 3. COOLDOWN (30 min): SOLO rifiuti reali, ancorati a rejected_at.
    --    Non conta le PROPOSED pendenti né i rifiuti di sistema (rejected_at IS NULL),
    --    ed esclude change_activity / dislike / superseded per consentire il reroll.
    SELECT COUNT(*) INTO var_recent_suggestion_count FROM activity_suggestions
    WHERE user_id = p_user_id
      AND status = 'REJECTED'
      AND rejected_at IS NOT NULL
      AND rejected_at > DATE_SUB(NOW(), INTERVAL 30 MINUTE)
      AND (rejection_reason IS NULL OR rejection_reason NOT IN ('change_activity', 'dislike', 'superseded'));
    IF var_recent_suggestion_count > 0 THEN SET p_state = 'SILENT_COOLDOWN'; LEAVE proc_exit; END IF;

    -- 4. ALLOW_NOTIFICATIONS sulla zona
    SELECT allow_notifications INTO var_allow_notif FROM beacons_catalog WHERE beacon_id = p_beacon_id;
    IF var_allow_notif = FALSE THEN SET p_state = 'SILENT_ZONE_DISABLED'; LEAVE proc_exit; END IF;

    -- 5. TRIGGER
    SET p_state = 'TRIGGER_FITNESS';
END //
DELIMITER ;