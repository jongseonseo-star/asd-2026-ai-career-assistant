# Group 19 - Release 1 Technical Report

GROUP 19  /  ADVANCED SOFTWARE DEVELOPMENT

AI Career AssistantRelease 1 Technical Report

Evidence-based group draft | 29 September 2026

Repository snapshot: 013053f, branch feature/student-4-release1. The Student 4 extension is committed locally but has not been pushed. Group identity follows the existing Release 0 report material; names and student IDs follow the team-supplied allocation table. [R1, R2]

1. Project overview and scope

The application supports career preparation through application tracking, resume improvement, interview practice and job exploration. Release 0 established feature-owned frontend, backend/API and database microservices with local AI Mode. Release 1 extends that foundation with one shared local MCP server, one shared local RAG server and a shared local agentic loop. AI processes remain outside Docker Compose. [R3]

The current checkout contains implementations for Students 2, 3 and 4. Student 2 provides resume-specific MCP/RAG support; Student 3 adds interview context retrieval and source metadata; Student 4 adds job-context tools and cited job guidance. The group must still establish complete Release 1 behavior across all participating features. This report distinguishes implemented code, captured runtime evidence and outstanding validation.

| Member / ID | Assigned feature | Release 1 position |

| Student 1: Melisa Soria
14482905 | Applications and cover letters | No participation this release, as confirmed by the team. No implementation in the inspected checkout. |

| Student 2: Tomohisa Tamao
25098094 | Resume and profile management | MCP/RAG implementation and automated tests present; hosted CI success verified for 320491b. |

| Student 3: David Saputra
14744662 | Interview preparation | Context retrieval and metadata implemented; integration gaps remain. |

| Student 4: Jongseon Seo
14603536 | Job listing management | Live frontend/API evidence and both shared loop modes captured. |

The allocation has four registered members; there is no Student 5. Individual assessment and any non-participation consequences remain the tutor's decision. The earlier report's Release 0 completion statements are not treated as proof of Release 1 completion.


---


2. Requirements and acceptance criteria

The following criteria translate the assessment brief into observable outcomes. They define the target group release; incomplete rows are not claimed as satisfied. [R3]

| ID | Functional requirement | Acceptance evidence |

| FR1 | Preserve each feature's CRUD and original AI Mode. | Frontend, API and database behavior remains usable after integration. |

| FR2 | Expose one shared local MCP service to every feature through its backend. | At least one valid structured tool result per feature; invalid inputs rejected. |

| FR3 | Retrieve relevant project context and generate grounded RAG answers. | Answers include usable source references and a confidence category. |

| FR4 | Handle insufficient context explicitly. | An unrelated query returns a no-context response without unsupported generation. |

| FR5 | Extend the shared loop with MCP and RAG validation modes. | Saved checks and model assessments from both modes; human review recorded separately. |

| FR6 | Retain containerised feature services and update CI. | Compose connects backends to host services; CI disables AI/MCP/RAG while testing feature services. |

Measurable non-functional requirements

| Quality | Target and rationale | Current evidence / limit |

| Security and boundaries | Only declared tool arguments; no caller-selected file paths or model configuration. Avoid cross-feature DB access. | Typed tools and owned-record checks for resumes/jobs; trusted localhost deployment, without authentication. |

| Traceability | Every generated job claim cites a record and retrieved guidance. Preserve chunk identity and source versions. | Citation validation and raw excerpts saved. Reference validity does not prove semantic accuracy. |

| Reliability | Missing records and unavailable dependencies produce explicit errors; no-context skips model generation. | Student 4 error/no-context tests and live negative query captured. |

| Performance | Bound requests: Student 4 MCP 15 s; backend RAG 210 s; frontend 240 s. | One live MCP request: 1.147 s; RAG answer: 3.826 s. These are observations, not a load benchmark. |

| Usability | Show answers, citations, confidence and readable failures in each feature UI. | Student 4 browser captures and rendering tests; group-wide UI acceptance remains open. |

| Maintainability / interoperability | Keep feature adapters small; use MCP, HTTP/JSON and backend-owned APIs. | Shared server, separate resume/jobs adapters and regression tests; no duplicate AI containers. |

| Availability | Document reproducible startup and return explicit dependency errors when host services stop. | Local execution only; no production uptime guarantee or failover is claimed. |


---


3. Release 1 architecture

Flask feature services communicate through HTTP APIs. Each database service alone owns its SQLite file. The shared home routes users to feature UIs; it does not bypass feature backends. Root Compose defines Student 2, 3 and 4 microservices and the shared home. AI Mode, MCP, RAG and the agentic loop run as host processes. [R4]

[Figure 1: Integrated components and Docker/host boundaries.]

Figure 1. Implemented group structure and explicit containerisation boundary. Student 3's missing host-service configuration is shown as an outstanding connection requirement.

Repository organisation

| Location | Purpose |

| student-2/, student-3/, student-4/ | Feature frontend, backend/API, database and tests. |

| ai-services/ | Shared MCP/RAG, feature generation adapters, retrieval, agentic loop and prompts. |

| ai-services/knowledge/ | Approved resume and jobs guidance. Interview guidance remains embedded in rag_server.py. |

| .github/workflows/ | Assigned student build and validation workflows. |

| docs/release-1/ | Captured evidence, contribution logs and known limitations. |

Students 2 and 4 configure host.docker.internal addresses in Compose; host processes use published database ports. Student 3 currently defaults to container loopback addresses and has no MCP/RAG environment entries in either Compose file. Therefore its shared-service integration is not established by the present root deployment. Student 1 contains only a README and directory placeholders.


---


4. MCP and RAG design

[Figure 2: Frontend-to-backend MCP retrieval and grounded RAG response flow.]

Figure 2. Resume/jobs grounded-response path. The no-context branch returns before model generation. Interview generation currently occurs in its feature backend and does not yet meet this shared-answer path.

| Registered MCP tool | Inputs and controlled output |

| resume_context | Positive profile/resume IDs; returns the owned profile, resume, skills and database references. |

| interview_context | Target role and interview type; returns structured guidance and evaluation dimensions. |

| job_context | Positive job ID; returns the posting, matching company, related skills and database references. |

| refresh_corpus / retrieve_context | Approved feature name; bounded query and top_k 1-5. Returns refresh metadata or cited chunks. |

| answer_question | Resume IDs, query and optional job description; obtains candidate context and invokes shared resume answering. |

The shared RAG service exposes /refresh, /retrieve and /answer. Resume and jobs retrieval split reviewed Markdown into chunks of at most 80 words, use deterministic 256-dimensional token-hash embeddings and persist vectors in local Chroma. Retrieval filters and ranks candidate chunks, retaining source URI, chunk ID, corpus version, text and similarity metadata. Refresh validates a new collection before activation. A lexical fallback is explicitly degraded and does not count as successful vector retrieval in loop validation. [R5]

The resume adapter generates four feedback sections; the jobs adapter generates concise claims. Source IDs identify evidence rather than model confidence: J references are job records and G references are retrieved guidance. Backend validation rejects unknown references or records inconsistent with the selected entity. Confidence reflects coverage and source authority: current authored guidance normally yields medium, while no relevant guidance yields low. High requires multiple qualifying authoritative sources and healthy retrieval.

Interview retrieval currently uses keyword matching over embedded guidance. Its backend displays source/confidence metadata, but it still calls Ollama when retrieval is empty and discards the returned MCP fields by reading a non-existent content wrapper. These are specific completion gaps, not capabilities demonstrated by the saved MCP status file. [R6]


---


5. Validation and observed results

Validation combined automated regression tests, live Docker-to-host requests, browser interaction and shared-loop execution. The saved run contains 231 passing tests across Student 4, shared services and Student 2; 21 Student 4 Release 1 cases were added. This is not 231 new tests or a group-wide live acceptance run. Model responses are mocked in automated cases; live model output is recorded separately. [R7]

| Layer | Observed result | Evidence |

| Automated behavior | Valid/invalid MCP inputs, record selection, citations, no-context, UI escaping and existing CRUD checked. | tests.txt; test_release1.py |

| Runtime integration | Student 4 backend/frontend and DB ready; MCP returned posting 2 and its matching records. | mcp-backend.json; readiness JSON; compose-ps.txt |

| RAG positive case | Two cited claims about unspecified required skills and the preferred Flask skill; medium confidence. | rag-backend.json; rag-frontend.json |

| RAG negative case | Weather query returned insufficient context, no claims and generation called=false. | rag-insufficient-context.json |

| Shared loop | MCP and RAG checks passed, with implementation and review model calls completed. | mcp-loop.json; rag-loop.json |

Live RAG used llama3.1:8b; loop assessments used qwen2.5:0.5b and llama3.1:8b. Both saved loop reviews passed automated execution checks, while human decisions remain pending. Job 2 was used because the preserved local database had 10 companies, 9 postings and 17 skills, with posting 1 already absent. No user data was reset for the demonstration.

Figure 3. Actual Student 4 browser guidance (left) and a transcription of the saved no-context API result (right). Original captures and JSON are retained in the evidence directory.

Negative-case API evidence: weather question; status insufficient-context; confidence low; no claims; model not called; duration 0.066 seconds.


---


6. DevOps and individual contributions

Student workflows build and smoke-test their containerised feature services. Students 2 and 4 explicitly disable Ollama and shared AI modes in CI; Student 3 sets AI_SERVICES_ENABLED=false in its workflow. The Student 4 backend image was also checked locally with both flags disabled: status reported disabled and MCP/RAG actions returned 503. These checks retain integration code without requiring host AI during CI.

| Hosted workflow | Verified successful run | Scope of that success |

| Student 2 | 36377715454 | 28 Sep 2026
Commit 320491b | Corrected Student 2 Release 1 branch. |

| Student 3 | 36375948122 | 28 Sep 2026
Commit dd0efee | Historical main revision; not the current local group snapshot. |

| Student 4 | 36378115766 | 28 Sep 2026
Commit 418fb6e | Before the new Student 4 Release 1 commits; updated workflow must run after push. |

Run states and commit identities were read from GitHub Actions on 29 September 2026. [R8-R10] A historical green workflow does not establish live MCP/RAG behavior or validate the unpushed Student 4 extension. No Student 1 workflow is present. Root and Student 4 Compose configurations were validated locally; captured running containers cover Student 4 and the shared home, not simultaneous operation of all features.

Individual contribution record

| Member | Implemented / recorded contribution | Identifiable commits |

| Melisa Soria | Team confirmed no participation in Release 1. No code, validation or showcase contribution was supplied for this report. | No Release 1 implementation identified. |

| Tomohisa Tamao | Resume MCP/RAG paths, cited output contract, vector retrieval, shared review-loop improvements and updated CI. | 320491b; merged through 418fb6e. Earlier preparation was reverted, so current attribution uses the corrected commit. |

| David Saputra | Initial shared MCP/RAG endpoints and local loop; interview prompt integration, source/status display and MCP evidence. | c64dc1e, 8dc1cc3, 07b254f, 9dbae86, b48c977. |

| Jongseon Seo | Shared job context/guidance; Student 4 UI/API integration; loop and regression tests; Compose/CI; live evidence and documentation. | 239e874, 8efcdb2, 71fbda5, 013053f. |

The commit history supports code attribution, not individual understanding or showcase attendance. Each participating student must verify their contribution description and explain their work during Q&amp;A. The Student 4 detailed contribution log is retained under docs/release-1/student-4/.


---


7. Limitations and submission completion

The report records the current implementation honestly rather than claiming group completion. Student 4 has the strongest current live evidence. Student 2 has code, regression coverage and a successful relevant hosted run, but its current-release frontend MCP/RAG and shared-loop outputs must be added to the final group evidence. Student 3 has historical MCP evidence and CI success; it still requires current integration repairs and live verification.

| Remaining item | Required completion |

| Student 1 non-participation | Retain the factual record and follow tutor guidance; do not substitute another student's work or claim absent evidence. |

| Student 3 integration | Pass host-service configuration into Compose, use returned MCP context correctly, and implement sufficient-context gating and the required shared RAG answer path. |

| Group demonstration | Run all participating features together; capture frontend, backend/API, DB and terminal evidence for each feature, with both loop modes. |

| Current CI and repository | Push the Student 4 commits, verify updated workflows against the submission revision, and ensure the tutor can access the repository. |

| Video and attendance | The showcase video URL is not yet available. Add one published video of at most 10 minutes; all members must attend the Week 9 showcase under the brief. |

| Final review | Confirm human assessments, contribution logs and final report details; one group member submits group-19.pdf by 4 October 2026, 11:59 PM AEST. |

Model and retrieval limitations remain: token-hash embeddings can miss synonyms; a small authored corpus cannot support every question; citations establish traceability rather than factual truth. Early job outputs omitted record citations or confused skill labels, leading to stricter citation structure and a clearer prompt. The inspected final job response matched its sources. The preserved original AI summary route responded successfully but repeated and added unsupported details; it is not evidence of answer accuracy. Local services are unauthenticated and depend on the demo machine.

Repository, evidence and references

Shared repository: https://github.com/jongseonseo-star/asd-2026-ai-career-assistant

Showcase video: not yet supplied by the team.

[R1] Existing Group 19 Release 0 report material; used only for group identity.

[R2] Team-supplied allocation screenshot and non-participation confirmation, 29 Sep 2026.

[R3] Release 1 assessment brief supplied in this session; 3,000-word report plus diagrams.

[R4] docker-compose.yml; docs/TEAM_RESPONSIBILITIES.md; feature service implementations.

[R5] ai-services/mcp_server.py, rag_server.py, rag_retrieval.py, resume_generation.py and job_generation.py.

[R6] student-3/backend/app.py; student-3/compose.local.yml; Student 3 MCP evidence JSON.

[R7] docs/release-1/student-4/evidence/ and contributions.md; source-manifest.json identifies implementation files.

[R8] Student 2 successful workflow - run 36377715454. GitHub conclusion: success.

[R9] Student 3 historical successful workflow - run 36375948122. GitHub conclusion: success.

[R10] Student 4 pre-extension successful workflow - run 36378115766. GitHub conclusion: success.
