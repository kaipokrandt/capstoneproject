# Product Requirements Document (PRD)
## Frontend System
### Balance Assessment Smart Insole Platform

---

# 1. Product Overview

The frontend is a web-based clinical interface for collecting, visualizing, and reviewing plantar pressure and balance assessment data from smart insole devices.

The system enables clinicians to:

• conduct guided balance assessments  
• visualize near-real-time pressure distribution  
• analyze Center of Pressure (CoP) movement  
• manage patient records  
• compare sessions over time  
• generate clinical reports  
• export structured results  

The frontend communicates with a centralized backend server deployed in a clinical environment and supports simultaneous connections from multiple devices.

---

# 2. Product Goals

The frontend must:

1. Provide an intuitive guided workflow for clinicians conducting balance assessments
2. Display real-time biomechanical visualizations during tests
3. Enable structured patient data management
4. Support session history review and comparison
5. Provide clinical-grade report preview and export
6. Allow device calibration and configuration management
7. Enable operation in a clinic environment with multiple concurrent devices
8. Minimize cognitive load during patient assessment
9. Provide reliable session feedback within 30 seconds after test completion

---

# 3. Target Users

Primary Users:
• Physical therapists
• Rehabilitation clinicians
• Clinical technicians

Secondary Users:
• Researchers studying gait and balance metrics
• Clinical administrators reviewing patient progress

---

# 4. Core User Workflows

## 4.1 Guided Assessment Workflow

Step 1 — Select or create patient  
Step 2 — Select assessment type  
Step 3 — Pair device  
Step 4 — Verify calibration  
Step 5 — Begin recording  
Step 6 — Monitor real-time visualizations  
Step 7 — End session  
Step 8 — Review results  
Step 9 — Add clinical notes  
Step 10 — Generate report  

---

## 4.2 Patient Management Workflow

Clinicians must be able to:

• search for existing patients
• create new patient profiles
• view patient session history
• edit patient metadata
• associate sessions with patient records

---

## 4.3 Session Review Workflow

Clinicians must be able to:

• review previous session visualizations
• compare sessions across time
• view computed metrics
• annotate sessions
• export results

---

# 5. Core Features

## 5.1 Real-Time Visualization

Frontend must display live data streams including:

• pressure heatmap of insole sensor grid
• Center of Pressure trajectory path
• stance symmetry indicators
• balance stability indicators
• device connection status

For prototype scope, visualizations update through frequent metrics/frame polling (not websocket streaming).

---

## 5.2 Session Comparison

Clinicians must be able to:

• compare multiple sessions for a patient
• visualize changes in CoP behavior
• visualize changes in pressure distribution
• observe trend metrics across time

---

## 5.3 Patient Record Interface

Each patient profile must contain:

• patient identifier
• session history
• stored reports
• annotation history
• associated metrics

---

## 5.4 Report Preview Interface

Frontend must provide preview of generated clinical report including:

• pressure distribution visualizations
• Center of Pressure trajectory plots
• computed balance metrics
• clinician notes
• device metadata
• timestamp information

---

## 5.5 Calibration Interface

Frontend must provide interface allowing clinicians to:

• initiate calibration sequence
• monitor calibration progress
• store calibration profiles
• re-run calibration when necessary

---

## 5.6 Device Management Interface

Frontend must allow clinicians to:

• view connected devices
• pair devices
• view device status
• initiate firmware update process
• monitor device connection quality

---

## 5.7 Annotation Capability

Clinicians must be able to attach notes to sessions including:

• contextual patient observations
• environmental factors
• clinician interpretation notes

---

## 5.8 Export Functionality

Frontend must allow exporting of:

• PDF clinical reports
• JSON session metrics
• session visualizations

---

# 6. Functional Requirements

FR1. System must support concurrent sessions across multiple devices  
FR2. System must display near-real-time heatmap visualization  
FR3. System must display near-real-time CoP trajectory  
FR4. System must allow creation of new patient records  
FR5. System must allow editing of patient metadata  
FR6. System must allow viewing historical sessions  
FR7. System must allow session comparison  
FR8. System must allow annotation of sessions  
FR9. System must allow report preview  
FR10. System must allow report export  
FR11. System must allow JSON metric export via backend API  
FR12. System must provide calibration interface  
FR13. System must support device pairing workflow  
FR14. System must support firmware update initiation  
FR15. System must provide guided workflow interface  

---

# 7. Non-Functional Requirements

NFR1. Visualization latency must remain below 1 second  
NFR2. UI must remain usable during concurrent device connections  
NFR3. UI must operate reliably within clinic network environment  
NFR4. System must provide responsive interaction performance  
NFR5. Interface must be usable by clinicians with minimal training  

---

# 8. Data Dependencies

Frontend consumes:

• pressure frame data streams
• computed gait metrics
• patient records
• calibration profiles
• session metadata
• report metadata

---

# 9. Constraints

• Must operate within clinical environment
• Must support multiple devices simultaneously
• Must support multiple patients
• Must support local-first operation
• Must support future Epic integration

---

# 10. Success Metrics

Primary metrics:

• successful session completion rate
• report generation latency
• clinician workflow completion time
• visualization responsiveness
• session comparison usability

---

# 11. Risks

• visualization complexity may impact performance
• concurrent device management complexity
• usability challenges for clinicians
• calibration usability issues
• data interpretation clarity
