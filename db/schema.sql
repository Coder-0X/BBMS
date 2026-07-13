-- Blood Bank Modular Starter schema reference

CREATE DATABASE IF NOT EXISTS blood_bank_db;
USE blood_bank_db;

CREATE TABLE donors (
    id INT AUTO_INCREMENT PRIMARY KEY,
    donor_code VARCHAR(30) NOT NULL UNIQUE,
    full_name VARCHAR(150) NOT NULL,
    blood_group VARCHAR(5) NOT NULL,
    rh_factor VARCHAR(10) NOT NULL,
    phone VARCHAR(30) NULL,
    email VARCHAR(120) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE donations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    donation_code VARCHAR(30) NOT NULL UNIQUE,
    donor_id INT NOT NULL,
    donation_datetime DATETIME NOT NULL,
    quantity_ml INT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'Collected',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_donations_donor FOREIGN KEY (donor_id) REFERENCES donors(id)
);

CREATE TABLE blood_tests (
    id INT AUTO_INCREMENT PRIMARY KEY,
    donation_id INT NOT NULL,
    abo_group VARCHAR(5) NOT NULL,
    rh_factor VARCHAR(10) NOT NULL,
    hemoglobin DECIMAL(5,2) NULL,
    hiv_result VARCHAR(20) NOT NULL DEFAULT 'Pending',
    hbv_result VARCHAR(20) NOT NULL DEFAULT 'Pending',
    hcv_result VARCHAR(20) NOT NULL DEFAULT 'Pending',
    syphilis_result VARCHAR(20) NOT NULL DEFAULT 'Pending',
    malaria_result VARCHAR(20) NOT NULL DEFAULT 'Pending',
    overall_result VARCHAR(10) NOT NULL DEFAULT 'Pass',
    tested_at DATETIME NOT NULL,
    CONSTRAINT fk_blood_tests_donation FOREIGN KEY (donation_id) REFERENCES donations(id)
);

CREATE TABLE blood_components (
    id INT AUTO_INCREMENT PRIMARY KEY,
    component_name VARCHAR(60) NOT NULL UNIQUE,
    description VARCHAR(255) NULL
);

CREATE TABLE blood_units (
    id INT AUTO_INCREMENT PRIMARY KEY,
    unit_code VARCHAR(40) NOT NULL UNIQUE,
    component_id INT NOT NULL,
    blood_group VARCHAR(5) NOT NULL,
    rh_factor VARCHAR(10) NOT NULL,
    quantity_ml INT NOT NULL,
    expiry_date DATE NOT NULL,
    unit_state VARCHAR(20) NOT NULL DEFAULT 'Available',
    CONSTRAINT fk_blood_units_component FOREIGN KEY (component_id) REFERENCES blood_components(id)
);

CREATE TABLE inventory (
    id INT AUTO_INCREMENT PRIMARY KEY,
    blood_unit_id INT NOT NULL UNIQUE,
    available_quantity INT NOT NULL,
    reserved_quantity INT NOT NULL DEFAULT 0,
    location VARCHAR(100) NULL,
    storage_status VARCHAR(20) NOT NULL DEFAULT 'Available',
    CONSTRAINT fk_inventory_unit FOREIGN KEY (blood_unit_id) REFERENCES blood_units(id)
);

CREATE TABLE patients (
    id INT AUTO_INCREMENT PRIMARY KEY,
    patient_code VARCHAR(30) NOT NULL UNIQUE,
    full_name VARCHAR(150) NOT NULL,
    gender VARCHAR(10) NULL,
    age INT NULL,
    phone VARCHAR(30) NULL,
    diagnosis VARCHAR(255) NULL
);

CREATE TABLE blood_requests (
    id INT AUTO_INCREMENT PRIMARY KEY,
    request_code VARCHAR(30) NOT NULL UNIQUE,
    patient_id INT NOT NULL,
    required_blood_group VARCHAR(5) NOT NULL,
    required_rh VARCHAR(10) NOT NULL,
    required_component VARCHAR(60) NOT NULL,
    units_required INT NOT NULL DEFAULT 1,
    request_status VARCHAR(20) NOT NULL DEFAULT 'Pending',
    request_date DATETIME NOT NULL,
    CONSTRAINT fk_blood_requests_patient FOREIGN KEY (patient_id) REFERENCES patients(id)
);

CREATE TABLE crossmatches (
    id INT AUTO_INCREMENT PRIMARY KEY,
    crossmatch_code VARCHAR(30) NOT NULL UNIQUE,
    blood_request_id INT NOT NULL,
    blood_unit_id INT NOT NULL,
    compatibility_result VARCHAR(20) NOT NULL,
    crossmatched_at DATETIME NOT NULL,
    CONSTRAINT fk_crossmatches_request FOREIGN KEY (blood_request_id) REFERENCES blood_requests(id),
    CONSTRAINT fk_crossmatches_unit FOREIGN KEY (blood_unit_id) REFERENCES blood_units(id)
);

CREATE TABLE blood_issues (
    id INT AUTO_INCREMENT PRIMARY KEY,
    issue_code VARCHAR(30) NOT NULL UNIQUE,
    crossmatch_id INT NOT NULL,
    issued_to_patient_id INT NOT NULL,
    doctor_name VARCHAR(150) NULL,
    hospital_name VARCHAR(150) NULL,
    issued_datetime DATETIME NOT NULL,
    issue_status VARCHAR(20) NOT NULL DEFAULT 'Issued',
    CONSTRAINT fk_blood_issues_crossmatch FOREIGN KEY (crossmatch_id) REFERENCES crossmatches(id),
    CONSTRAINT fk_blood_issues_patient FOREIGN KEY (issued_to_patient_id) REFERENCES patients(id)
);

CREATE TABLE staff_profile (
    id INT AUTO_INCREMENT PRIMARY KEY,
    employee_code VARCHAR(30) NOT NULL UNIQUE,
    role_name VARCHAR(50) NOT NULL,
    phone VARCHAR(30) NULL
);

CREATE TABLE audit_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    action_type VARCHAR(100) NOT NULL,
    module_name VARCHAR(100) NOT NULL,
    record_id INT NULL,
    description TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
