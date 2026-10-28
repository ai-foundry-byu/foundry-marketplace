# {{PROJECT_NAME}}: decisions

Every decision a human made, in their words, with what it authorizes and what it does not. Agents propose; humans decide. An agent never writes a row here that a human did not say.

| Id | Date | Who | The decision (verbatim) | What it authorizes | What still needs a human |
|---|---|---|---|---|---|
| D-01 | {{DATE}} | TODO: role | TODO: "exact words" | TODO: e.g. build R-01 to R-04 with the free tier of the database | TODO: e.g. any paid plan, any email to real users |

When the human approves the PRD (stage 2 exit), add a row whose "What it authorizes" cell starts with `PRD approved`, for example `| D-04 | 2026-11-02 | product owner | "Approved." | PRD approved: PRD.md v0.1 and stories US-01 to US-09 | the workplan starts when they ask |`. The stage detector looks for that dated row.

## Pending decisions (ask these, with a recommendation)

Write each as a question with your recommended answer in bold, so the human can answer with one word. When one is answered, add its D-row above and delete it from this list in the same edit.

1. TODO: Should sign-in use magic links or passwords? **Recommendation: magic links** (no password reset flow to build; the audit found the school SSO is not available to us).
