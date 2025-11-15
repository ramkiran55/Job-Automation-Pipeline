# Job Automation Pipeline - Master Documentation

## Project Overview
An AWS-based serverless job application automation system that scrapes job boards, filters by criteria, manages referral outreach, and handles follow-ups.

**Developer**: Ram Kiran Devireddy  
**Tech Focus**: AWS Data Engineering + NoSQL (DynamoDB)  
**Timeline**: 1-2 week MVP  
**Cost**: $0 (AWS Free Tier)

---

## Project Goals

### Primary Objectives
1. **Automate job discovery** across multiple platforms
2. **Filter jobs** based on skills, salary, visa sponsorship
3. **Manage referral outreach** with AI-generated emails
4. **Track application status** through entire lifecycle
5. **Add resume-worthy skills**: DynamoDB, event-driven architecture, serverless orchestration

### Success Metrics
- 40-100 relevant jobs discovered per week
- 80%+ match accuracy for skill filtering
- Automated referral email generation
- Zero infrastructure costs

---

## System Architecture

### High-Level Overview
```
EventBridge (cron) 
    ↓
Step Functions Orchestrator
    ├─ Stage 1: Job Discovery (3 parallel Lambda scrapers)
    ├─ Stage 2: Referral Outreach (LinkedIn scraping + AI emails)
    └─ Stage 3: Follow-ups (Recruiter outreach)
    ↓
DynamoDB (central data store)
    ↓
S3 (raw data lake)
```

### Stage 1: Job Discovery Pipeline (Current Focus)
```
┌──────────────────────────────────────────────────────────────┐
│  EventBridge Rule (daily 6 AM & 6 PM ET)                    │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  Step Functions: JobScraperOrchestrator                     │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 1. Parallel State (scrape all sources)             │   │
│  │    ├─ Lambda: scrape-linkedin (15 min)             │   │
│  │    ├─ Lambda: scrape-indeed (15 min)               │   │
│  │    └─ Lambda: scrape-greenhouse (15 min)           │   │
│  └──────────────────┬──────────────────────────────────┘   │
│                     │                                        │
│  ┌──────────────────▼──────────────────────────────────┐   │
│  │ 2. Lambda: deduplicate-and-filter                   │   │
│  │    - Remove duplicates across sources               │   │
│  │    - Filter by skills, salary, visa                 │   │
│  │    - Calculate match score                          │   │
│  └──────────────────┬──────────────────────────────────┘   │
│                     │                                        │
│  ┌──────────────────▼──────────────────────────────────┐   │
│  │ 3. Lambda: batch-write-dynamodb                     │   │
│  │    - Batch write (25 items per batch)               │   │
│  └──────────────────┬──────────────────────────────────┘   │
│                     │                                        │
│  ┌──────────────────▼──────────────────────────────────┐   │
│  │ 4. Lambda: send-summary-email (SNS)                 │   │
│  │    - Daily summary notification                     │   │
│  └─────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
                         │
            ┌────────────┴────────────┐
            ▼                         ▼
    ┌──────────────┐        ┌──────────────┐
    │  S3 Bucket   │        │  DynamoDB    │
    │  Raw Scrapes │        │  jobs table  │
    └──────────────┘        └──────────────┘
```

---

## Tech Stack

### Core Infrastructure (All AWS Free Tier)
- **Compute**: AWS Lambda (Python 3.11)
  - 1M requests/month free
  - 400K GB-seconds compute free
  - 15 min max timeout
- **Database**: DynamoDB
  - 25 GB storage free
  - 25 WCU/RCU free
- **Orchestration**: AWS Step Functions
  - 4,000 state transitions/month free
- **Scheduling**: Amazon EventBridge
  - All events free
- **Storage**: Amazon S3
  - 5 GB free (first 12 months)
- **Notifications**: Amazon SNS
  - 1,000 emails/month free
- **IaC**: Terraform + GitHub Actions (CI/CD)

### Development Tools
- **Language**: Python 3.11+
- **Web Scraping**: Playwright (headless Chrome)
- **AI**: Anthropic Claude API (for Stage 2 emails)
- **Email**: Gmail SMTP or SendGrid
- **Version Control**: Git + GitHub
- **Local Testing**: LocalStack (optional)

### Why This Stack?
1. **100% Free** on AWS Free Tier
2. **Serverless** - no servers to manage
3. **Scalable** - handles growth automatically
4. **Resume-worthy** - AWS + DynamoDB + event-driven architecture
5. **Fast to build** - managed services, less boilerplate

---

## Data Model

### DynamoDB Table: `jobs`

**Primary Key**:
- Partition Key: `job_id` (String) - Format: `{source}_{unique_id}`

**Attributes**:
```python
{
  # Primary Key
  "job_id": "linkedin_12345678",
  
  # Job Metadata
  "source": "linkedin",                    # linkedin, indeed, greenhouse
  "company_name": "Amazon",
  "job_title": "Senior Data Engineer",
  "location": "Seattle, WA",
  "work_mode": "hybrid",                   # remote, onsite, hybrid
  
  # Matching Criteria
  "skills": ["Python", "AWS", "Spark"],    # List of matched skills
  "salary_min": 150000,                    # Integer
  "salary_max": 200000,                    # Integer
  "visa_sponsorship": true,                # Boolean
  
  # Content
  "job_description": "Full description...",
  "application_link": "https://...",
  
  # Tracking
  "posted_date": "2024-11-12",            # ISO date
  "scraped_at": "2024-11-12T18:00:00Z",   # ISO timestamp
  "status": "new",                         # new -> interested -> applied -> followed_up -> rejected
  "match_score": 0.85,                     # 0.0 to 1.0
  
  # Auto-cleanup
  "ttl": 1734000000                        # Unix timestamp (90 days from scrape)
}
```

**Global Secondary Indexes (GSI)**:

**GSI1: `status-date-index`**
- Partition Key: `status`
- Sort Key: `posted_date`
- Use case: "Get all 'interested' jobs, newest first"

**GSI2: `skills-index`**
- Partition Key: `skill` (requires flattening skills array)
- Sort Key: `match_score`
- Use case: "Find all AWS jobs, best matches first"

**Capacity Settings**:
- On-demand pricing (pay per request)
- Or provisioned: 5 RCU / 5 WCU (well within free tier)

---

## Lambda Functions Specification

### 1. `scrape-linkedin`
**Purpose**: Scrape LinkedIn Jobs  
**Runtime**: Python 3.11  
**Timeout**: 15 minutes  
**Memory**: 2048 MB  
**Layers**: playwright-layer (Chromium binary)  
**Environment Variables**:
- `S3_BUCKET`: job-scraper-raw
- `TARGET_ROLES`: Data Engineer, Senior Data Engineer
- `TARGET_LOCATIONS`: United States, Remote

**Input**: None (triggered by Step Functions)  
**Output**: 
```json
{
  "statusCode": 200,
  "jobs": [...],
  "count": 47
}
```

### 2. `scrape-indeed`
**Purpose**: Scrape Indeed Jobs  
**Config**: Same as scrape-linkedin  

### 3. `scrape-greenhouse`
**Purpose**: Scrape Greenhouse boards (company career pages)  
**Config**: Same as scrape-linkedin  
**Note**: Greenhouse is easier (less JS-heavy)

### 4. `deduplicate-and-filter`
**Purpose**: Filter jobs by criteria  
**Runtime**: Python 3.11  
**Timeout**: 5 minutes  
**Memory**: 512 MB  
**Environment Variables**:
- `MY_SKILLS`: Python,AWS,Spark,Terraform,Glue,Redshift,ETL
- `MIN_SALARY`: 100000
- `REQUIRED_VISA`: true
- `MIN_SKILL_MATCHES`: 3

**Input**: Array of scraper outputs  
**Output**:
```json
{
  "statusCode": 200,
  "jobs": [...],  // Filtered & enriched
  "count": 23
}
```

### 5. `batch-write-dynamodb`
**Purpose**: Write filtered jobs to DynamoDB  
**Runtime**: Python 3.11  
**Timeout**: 2 minutes  
**Memory**: 256 MB  
**Environment Variables**:
- `DYNAMODB_TABLE`: jobs

### 6. `send-summa