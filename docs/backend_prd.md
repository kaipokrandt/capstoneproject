# Product Requirements Document (PRD)
## Backend System
### Balance Assessment Smart Insole Platform

Last Verified: 2026-04-11  
Owner: Product + Backend Engineering  
Code References: `wbs/wbs/sessions_views.py`, `wbs/wbs/reports_views.py`, `wbs/wbs/master_views.py`  
Test References: `wbs/wbs/tests/test_sessions_api.py`, `wbs/wbs/tests/test_reports_api.py`, `wbs/wbs/tests/test_master_api.py`

---

# 1. Product Overview

The backend system processes biomechanical pressure data collected from smart insoles and provides infrastructure for storage, analysis, reporting, and clinical integration.

The backend serves multiple devices simultaneously within a clinical environment and supports structured patient record management.

The system stores raw sensor data, computed gait metrics, and clinical reports, enabling longitudinal analysis of balance performance.

---

# 2. Product Goals

The backend must:

1. ingest real-time pressure data streams from multiple devices
2. process biomechanical signals to derive clinically relevant metrics
3. store structured patient and session data
4. generate clinical reports
5. provide structured data interfaces for frontend visualization
6. support concurrent device connections
7. support calibration profile management
8. provide extensibility for future Epic FHIR integration
9. support local-first clinical deployment

---

# 3. System Scope

Backend responsibilities include:

• device data ingestion
• session orchestration
• signal processing pipeline
• metric computation
• structured data storage
• report generation
• mock FHIR adapter interface
• calibration data management
• device management support

---

# 4. Core Data Flow

Device → Backend ingestion → signal processing → metric computation → database storage → report generation → frontend retrieval → optional EMR integration

---

# 5. Core Features

## 5.1 Data Ingestion

Backend must support:

• simultaneous connections from multiple devices
• continuous streaming of pressure data
• session segmentation
• timestamp synchronization
• device identification

---

## 5.2 Signal Processing Pipeline

Backend must support processing of pressure data to produce:

• Center of Pressure trajectory
• balance stability metrics
• symmetry metrics
• temporal gait features
• spatial pressure distribution metrics

---

## 5.3 Session Management

Backend must support:

• creation of sessions
• association of sessions with patients
• storage of session metadata
• retrieval of historical sessions
• concurrent session handling

---

## 5.4 Patient Record Management

Backend must store:

• patient identifiers
• patient metadata
• associated sessions
• associated reports
• annotation metadata

---

## 5.5 Calibration Profile Management

Backend must support:

• storing calibration profiles
• retrieving calibration profiles
• associating calibration profiles with devices
• updating calibration profiles

---

## 5.6 Raw Data Storage

Backend must store:

• raw pressure frames
• timestamps
• device identifiers
• session identifiers

Raw data must remain accessible for future analysis.

---

## 5.7 Metric Storage

Backend must store computed metrics including:

• Center of Pressure trajectory
• stability indices
• symmetry indices
• temporal metrics
• spatial metrics

---

## 5.8 Report Generation

Backend must support generation of structured clinical reports containing:

• computed metrics
• visualization outputs
• clinician annotations
• session metadata
• device metadata

Reports must be exportable in PDF format.

---

## 5.9 Mock FHIR Adapter

Backend must include an adapter layer capable of:

• mapping computed metrics to standardized clinical resources
• structuring observations in FHIR-compatible format
• enabling future integration with EMR systems

---

## 5.10 Device Management Support

Backend must support:

• device registration
• device association with sessions
• device metadata storage
• firmware version tracking

---

# 6. Functional Requirements

FR1. System must support concurrent device connections  
FR2. System must store raw pressure data  
FR3. System must store computed metrics  
FR4. System must associate sessions with patients  
FR5. System must support session retrieval  
FR6. System must store calibration profiles  
FR7. System must generate PDF reports  
FR8. System must support annotation storage  
FR9. System must provide structured API for frontend  
FR10. System must support mock FHIR adapter layer  
FR11. System must maintain session timestamps  
FR12. System must support multi-patient architecture  
FR13. System must support multi-device architecture  

---

# 7. Non-Functional Requirements

NFR1. System must support real-time data ingestion  
NFR2. System must support concurrent device streams  
NFR3. System must support reliable local deployment  
NFR4. System must support extensibility for EMR integration  
NFR5. System must maintain data consistency  
NFR6. System must support secure storage practices  

---

# 8. Data Entities

Core entities:

• patient
• session
• raw_frame
• computed_metric
• calibration_profile
• device
• report
• annotation

---

# 9. Constraints

---

# PRD vs Implemented (Current Drift Notes)

This PRD remains the intent document. Implemented behavior is documented in:
- `docs/backend/backend_handbook.md`
- `docs/api/api_reference.md`
- `docs/data/data_model_reference.md`

Notable implementation additions beyond the original PRD wording:
- Weekly rollup report generation (`scope=weekly`) with Mon-Sun aggregation and anchor-session storage.
- Clinician UI preference persistence endpoint (`/api/ui-preferences/`) for sensor layout calibration.
- Device firmware/calibration simulated job tracking integrated through device metadata and calibration profile creation.

• local-first architecture
• relational database storage
• concurrent device operation
• future Epic integration compatibility
• storage of raw sensor data

---

# 10. Success Metrics

Primary metrics:

• successful session ingestion rate
• report generation latency
• system uptime
• concurrent session handling reliability
• data retrieval performance

---

# 11. Risks

• high-frequency data storage volume
• concurrent session scaling complexity
• metric computation consistency
• integration complexity with clinical systems
• calibration accuracy dependencies
