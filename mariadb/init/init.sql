CREATE DATABASE IF NOT EXISTS flowmate_db;
USE flowmate_db;

--DROP USER IF EXISTS 'user'@'%';

--CREATE USER 'user'@'%' IDENTIFIED BY 'userpassword';
--GRANT ALL PRIVILEGES ON flowmate_db.* TO 'user'@'%' IDENTIFIED BY 'userpassword';
--FLUSH PRIVILEGES;

-- Users Table
CREATE TABLE users (
    user_id CHAR(36) DEFAULT UUID() PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    weight_kg DECIMAL(5,2) NOT NULL,
    daily_kcal_goal INT NOT NULL,
    registration_date DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

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

-- Biometric Logs (Transactional)
CREATE TABLE biometric_logs (
    log_id CHAR(36) DEFAULT UUID() PRIMARY KEY,
    user_id CHAR(36),
    log_timestamp DATETIME NOT NULL,
    steps_recorded INT NOT NULL,
    kcal_burned INT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Completed Activities Log
CREATE TABLE completed_activities (
    activity_id CHAR(36) DEFAULT UUID() PRIMARY KEY,
    user_id CHAR(36),
    hobby_id INT,
    duration_minutes INT NOT NULL,
    completion_timestamp DATETIME NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (hobby_id) REFERENCES hobbies_catalog(hobby_id) ON DELETE RESTRICT
) ENGINE=InnoDB;

-- Chat History (Conversational Memory)
CREATE TABLE chat_history (
    message_id CHAR(36) DEFAULT UUID() PRIMARY KEY,
    user_id CHAR(36),
    sender_role VARCHAR(20),
    message_content TEXT NOT NULL,
    message_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_role CHECK (sender_role IN ('user', 'assistant', 'system')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Beacons Catalog (Registro Hardware aggiornato!)
CREATE TABLE beacons_catalog (
    beacon_id CHAR(36) DEFAULT UUID() PRIMARY KEY,
    user_id CHAR(36) NOT NULL,
    hardware_uuid VARCHAR(36) NOT NULL,
    major_id INT NOT NULL,
    minor_id INT NOT NULL,
    zone_name VARCHAR(100) NOT NULL,
    associated_hobby_id INT,
    UNIQUE (hardware_uuid, major_id, minor_id),
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

-- Performance Optimization Indexes (B-Tree)
CREATE INDEX idx_biometric_logs_user_time ON biometric_logs(user_id, log_timestamp DESC);
CREATE INDEX idx_chat_history_user_time ON chat_history(user_id, message_timestamp DESC);
CREATE INDEX idx_schedule_user_day ON silent_schedule(user_id, day_of_week);

-- Seed Data Initialization
INSERT INTO hobbies_catalog (hobby_name, met_value) VALUES
('Light Walking', 3.5),
('Basketball', 8.0),
('Running', 10.0),
('Gaming', 1.5),
('Reading', 1.3);