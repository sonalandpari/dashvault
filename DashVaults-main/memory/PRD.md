# Unbiased AI Decision — Fairness Audit Platform

## Problem Statement
[Unbiased AI Decision] Ensuring Fairness and Detecting Bias in Automated Decisions. Computer programs now make life-changing decisions about who gets a job, a bank loan, or even medical care. These programs learn from flawed/unfair historical data and amplify discriminatory mistakes. Build a solution to inspect datasets and models for hidden unfairness, measure bias, flag it, and recommend fixes before systems impact real people.

## Stack
- **Frontend**: React 19 + Tailwind + Shadcn UI + Recharts + framer-motion
- **Backend**: FastAPI + MongoDB (motor) + pandas + emergentintegrations
- **Auth**: JWT (httpOnly cookies) + bcrypt
- **Storage**: Emergent Object Storage (CSV uploads)
- **LLM**: Gemini 3 Flash (`gemini-3-flash-preview`) via emergentintegrations

## User Personas
1. **Compliance officer / AI ethics lead** — runs fairness audits on HR, credit, healthcare datasets.
2. **Data scientist** — inspects their training data before model release.
3. **Executive / auditor** — reads Gemini-generated plain-English reports & mitigations.

## Core Requirements (static)
- User authentication (email/password, JWT cookie).
- At least one cloud storage → Emergent Object Storage.
- Gemini API for bias explanations.

## Implemented (2026-02-15)
- JWT auth (register / login / logout / me) + admin seeded
- CSV upload to Emergent Object Storage, metadata stored in Mongo
- Fairness metrics: demographic parity Δ, disparate impact ratio, statistical parity Δ, 4/5 rule, severity high/medium/low
- Gemini 3 Flash explanation + mitigation playbook
- Downloadable plain-text report
- Landing / Login / Register / Dashboard / Analyze / Analysis detail pages
- Swiss high-contrast design (Space Grotesk + JetBrains Mono + Inter)
- Recharts monochrome bar chart with red flag bars for biased groups
- data-testid attributes on all key interactive elements

## Backlog / Next Actions
- P1: Support multi-attribute bias (intersectional: gender × race)
- P1: Model auditing (upload predictions + labels for equal opportunity / equalized odds)
- P1: Dataset preview table in analysis detail
- P2: PDF report export
- P2: Team workspaces + shareable audit links
- P2: Brute-force lockout on login
- P2: Comma-separated CORS_ORIGINS to support multiple deploy hosts
- P2: Dataset mitigation preview (resampling / reweighting) before retraining

## Credentials
See `/app/memory/test_credentials.md`.
