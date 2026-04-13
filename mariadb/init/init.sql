-- ==============================================================================
-- INIZIALIZZAZIONE AMBIENTE
-- ==============================================================================
DROP DATABASE IF EXISTS flowmate_db;
CREATE DATABASE flowmate_db;
USE flowmate_db;

-- ==============================================================================
-- TABELLE CORE UTENTE
-- ==============================================================================

-- Users Table
CREATE TABLE users (
    user_id CHAR(36) DEFAULT UUID() PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    weight_kg DECIMAL(5,2) NOT NULL,
    daily_kcal_goal INT NOT NULL,
    daily_steps_goal INT NOT NULL DEFAULT 10000,
    registration_date DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ==============================================================================
-- CATALOGHI E DIZIONARI
-- ==============================================================================

-- Hobbies Catalog (Static Dictionary)
CREATE TABLE hobbies_catalog (
    hobby_id INT AUTO_INCREMENT PRIMARY KEY,
    hobby_name VARCHAR(100) UNIQUE NOT NULL,
    met_value DECIMAL(4,2) NOT NULL
) ENGINE=InnoDB;

-- User Hobbies Pivot Table (N:M Relationship)
CREATE TABLE user_hobbies (
    user_id CHAR(36),
    hobby_id INT,
    preference_level INT,
    PRIMARY KEY (user_id, hobby_id),
    CONSTRAINT chk_preference CHECK (preference_level >= 1 AND preference_level <= 5),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (hobby_id) REFERENCES hobbies_catalog(hobby_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ==============================================================================
-- CONTESTO TEMPORALE E BIOMETRICO
-- ==============================================================================

-- Silent Schedule (Availability Matrix)
CREATE TABLE silent_schedule (
    event_id CHAR(36) DEFAULT UUID() PRIMARY KEY,
    user_id CHAR(36),
    day_of_week INT,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    CONSTRAINT chk_day CHECK (day_of_week >= 0 AND day_of_week <= 6),
    CONSTRAINT chk_time CHECK (start_time < end_time),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Biometric Logs (Una riga per utente al giorno - Sincronizzato con Health Connect)
CREATE TABLE biometric_logs (
    user_id CHAR(36),
    record_date DATE NOT NULL,
    steps_recorded INT DEFAULT 0,
    active_minutes INT DEFAULT 0,
    kcal_burned INT DEFAULT 0,
    PRIMARY KEY (user_id, record_date),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ==============================================================================
-- INFRASTRUTTURA HARDWARE (BEACONS E RATE LIMITING)
-- ==============================================================================

-- Beacons Catalog (Registro Hardware con Macchina a Stati Integrata)
CREATE TABLE beacons_catalog (
    beacon_id CHAR(36) DEFAULT UUID() PRIMARY KEY,
    user_id CHAR(36) NOT NULL,
    hardware_uuid VARCHAR(36) NOT NULL,
    major_id INT NOT NULL,
    minor_id INT NOT NULL,
    zone_name VARCHAR(100) NOT NULL,
    associated_hobby_id INT,
    allow_notifications BOOLEAN DEFAULT FALSE,
    UNIQUE (user_id, hardware_uuid, major_id, minor_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (associated_hobby_id) REFERENCES hobbies_catalog(hobby_id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- Zone Presence Logs (Transazioni di permanenza)
CREATE TABLE zone_presence_logs (
    presence_id CHAR(36) DEFAULT UUID() PRIMARY KEY,
    user_id CHAR(36) NOT NULL,
    beacon_id CHAR(36) NOT NULL,
    entry_timestamp DATETIME NOT NULL,
    exit_timestamp DATETIME,
    duration_minutes INT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (beacon_id) REFERENCES beacons_catalog(beacon_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Sent Notifications (Rate Limiting per evitare Spam)
CREATE TABLE sent_notifications (
    notification_id CHAR(36) DEFAULT UUID() PRIMARY KEY,
    user_id CHAR(36) NOT NULL,
    beacon_id CHAR(36) NOT NULL,
    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (beacon_id) REFERENCES beacons_catalog(beacon_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ==============================================================================
-- LOGICA FUNZIONALE E STORICO
-- ==============================================================================

-- Activity Suggestions Log (Tracciamento ciclo di vita raccomandazioni)
CREATE TABLE activity_suggestions (
    suggestion_id CHAR(36) DEFAULT UUID() PRIMARY KEY,
    user_id CHAR(36) NOT NULL,
    hobby_id INT NOT NULL,
    suggested_duration_minutes INT NOT NULL,
    expected_kcal INT NOT NULL, 
    baseline_active_minutes INT DEFAULT 0, 
    status VARCHAR(20) DEFAULT 'PROPOSED', 
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME, 
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (hobby_id) REFERENCES hobbies_catalog(hobby_id) ON DELETE RESTRICT
) ENGINE=InnoDB;

-- Chat History (Memoria per LLM)
CREATE TABLE chat_history (
    message_id CHAR(36) DEFAULT UUID() PRIMARY KEY,
    user_id CHAR(36),
    sender_role VARCHAR(20),
    message_content TEXT NOT NULL,
    message_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_role CHECK (sender_role IN ('user', 'assistant', 'system')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ==============================================================================
-- OTTIMIZZAZIONE E SEED DATA
-- ==============================================================================

-- Performance Optimization Indexes (B-Tree)
CREATE INDEX idx_biometric_logs_user_time ON biometric_logs(user_id, record_date DESC);
CREATE INDEX idx_chat_history_user_time ON chat_history(user_id, message_timestamp DESC);
CREATE INDEX idx_schedule_user_day ON silent_schedule(user_id, day_of_week);
CREATE INDEX idx_sent_notifications_time ON sent_notifications(user_id, beacon_id, sent_at DESC);
CREATE INDEX idx_suggestions_user_status ON activity_suggestions(user_id, status);

-- Seed Data Initialization
INSERT INTO hobbies_catalog (hobby_name, met_value) VALUES
('Light Walking', 3.5),
('Basketball', 8.0),
('Running', 10.0),
('Gaming', 1.5),
('Reading', 1.3);


-- ==============================================================================
-- MACCHINA A STATI FINITI (STORED PROCEDURE AGGIORNATA)
-- ==============================================================================

DELIMITER //

CREATE PROCEDURE EvaluateProactiveState(
    IN p_user_id CHAR(36),
    IN p_beacon_id CHAR(36),
    OUT p_action_state VARCHAR(50)
)
BEGIN
    DECLARE v_allow_notifications BOOLEAN DEFAULT FALSE;
    DECLARE v_recent_spam_count INT DEFAULT 0;
    DECLARE v_pending_proposals INT DEFAULT 0;
    DECLARE v_is_free_time INT DEFAULT 0;
    DECLARE v_kcal_goal INT DEFAULT 0;
    DECLARE v_kcal_burned INT DEFAULT 0;
    
    DECLARE v_current_day INT;
    DECLARE v_current_time TIME;

    SET v_current_day = WEEKDAY(CURRENT_DATE());
    SET v_current_time = CURRENT_TIME();

    -- 1. Controllo se la zona del beacon permette notifiche
    SELECT allow_notifications INTO v_allow_notifications 
    FROM beacons_catalog 
    WHERE beacon_id = p_beacon_id AND user_id = p_user_id;

    -- 2. Controllo Rate Limiting (Spam): max 1 notifica per ora per questo beacon
    SELECT COUNT(*) INTO v_recent_spam_count 
    FROM sent_notifications 
    WHERE user_id = p_user_id AND beacon_id = p_beacon_id AND sent_at >= NOW() - INTERVAL 1 HOUR;

    -- 3. Controllo Proposte Pendenti: se c'è già un PROPOSED attivo oggi, non disturbare
    SELECT COUNT(*) INTO v_pending_proposals 
    FROM activity_suggestions 
    WHERE user_id = p_user_id 
      AND status = 'PROPOSED' 
      AND DATE(created_at) = CURRENT_DATE();

    -- 4. Controllo Calendario: l'utente deve essere in un blocco "Free Time"
    SELECT COUNT(*) INTO v_is_free_time 
    FROM silent_schedule 
    WHERE user_id = p_user_id 
      AND day_of_week = v_current_day 
      AND start_time <= v_current_time 
      AND end_time >= v_current_time
      AND event_type = 'Free Time';

    -- 5. Recupero obiettivi e progresso odierno
    SELECT daily_kcal_goal INTO v_kcal_goal FROM users WHERE user_id = p_user_id;
    
    SELECT IFNULL(kcal_burned, 0) INTO v_kcal_burned 
    FROM biometric_logs 
    WHERE user_id = p_user_id AND record_date = CURRENT_DATE();

    -- ==========================================================================
    -- LOGICA DI USCITA (GERARCHIA)
    -- ==========================================================================
    IF v_allow_notifications = FALSE THEN
        SET p_action_state = 'SILENT_DND_ZONE';
    ELSEIF v_recent_spam_count > 0 THEN
        SET p_action_state = 'SILENT_RATE_LIMITED';
    ELSEIF v_pending_proposals > 0 THEN
        SET p_action_state = 'SILENT_PROPOSAL_PENDING';
    ELSEIF v_is_free_time = 0 THEN
        SET p_action_state = 'SILENT_BUSY_SCHEDULE';
    ELSEIF v_kcal_burned < v_kcal_goal THEN
        SET p_action_state = 'TRIGGER_FITNESS';
    ELSE
        SET p_action_state = 'TRIGGER_HOBBY';
    END IF;

END //

DELIMITER ;