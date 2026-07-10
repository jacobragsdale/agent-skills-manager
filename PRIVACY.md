# Privacy and retention

Agent Skills telemetry exists to improve shared skills and diagnose broken
installation paths. It is not intended to measure individual productivity,
rank developers, reconstruct conversations, or inspect source code.

## Data collected

Local event schema version 1 permits only:

- random installation UUID (`machine_id`);
- random event and invocation UUIDs;
- UTC event timestamp;
- event type;
- skill name and skills-repository Git SHA;
- agent surface name and optional client version;
- outcome: `unknown`, `ok`, `corrected`, `failed`, or `abandoned`;
- optional correction category;
- for a learning only, one factual message of at most 2,000 characters;
- for a heartbeat only, the installed runtime Git SHA.

The event validator rejects unknown fields. This is intentional: adding a field
requires an explicit schema and privacy review rather than silently expanding
collection.

## Data not collected

Do not record:

- prompts, responses, reasoning, or conversation transcripts;
- source code, diffs, generated code, file names, or repository paths;
- repository names, URLs, branch names, ticket numbers, or customer names;
- Windows username, email address, hostname, device serial, or IP address;
- secrets, tokens, credentials, internal endpoints, or proprietary identifiers;
- timing, keystrokes, task duration, or productivity scores.

Skill instructions explicitly tell the agent not to place these values in a
learning. Free-text learning events are nevertheless treated as untrusted and
must be reviewed before merge.

## Identity and access

`machine_id` is a random UUID generated at installation. It is not derived from
a person or device attribute. The inbox Git provider can still retain normal
authentication and push audit logs, so the system is pseudonymous rather than
anonymous.

- Developers can read the reviewed skills repository.
- Developers can create and update inbox branches, but cannot push protected
  skills `main`.
- Maintainers can read inbox refs and create aggregation pull requests.
- Reviewers see proposed aggregate metrics and learning text before merge.
- Cursor's by-user Analytics endpoint is disabled by default. Enabling it
  requires a documented need and team approval because it exposes user-level
  activity.

## Retention

| Data | Retention |
|---|---|
| Local pending events | Until a successful inbox push |
| Local sent events | 7 days |
| Local quarantined events and reason files | 30 days |
| Raw monthly inbox branches | 45 days after the branch month closes, after successful aggregation |
| Processed event-ID deduplication index | 13 months |
| Per-machine fleet heartbeat state | Last observation while active; remove after 45 days of silence |
| Aggregated skill metrics | 13 months |
| Rejected-event summaries | 13 months, without raw event bodies |
| Reviewed learnings merged into a skill | Part of normal repository history |

The local manager enforces local sent/quarantine cleanup. Maintainers rotate
and delete processed monthly inbox branches and prune repository aggregates as
operational tasks; automation for those server-side policies is a pilot gate.
Git branch deletion is not guaranteed secure erasure until the server
garbage-collects unreachable objects. If contractual deletion guarantees
become necessary, raw event transport must move from Git to storage with
enforceable lifecycle policies.

## Metrics interpretation

`recorded_invocations` counts only start events the agent successfully wrote.
It is a lower-bound operational signal, not adoption and not proof that the
skill was needed or successful.

Outcome and correction rates are also lower-bound reports. Users differ in how
often they correct agents, and the agent can omit a finish event. Dashboard
language must retain these qualifications.

Cursor's Enterprise Skill Adoption endpoint is an independent, platform-side
daily aggregate. Keep it separate from local events. Validate user-scoped skill
coverage with a canary before using it, and never infer an individual's
performance from either source.

## Incident handling

If an event contains prohibited or sensitive content:

1. Do not copy it into a pull request or issue.
2. Quarantine the affected branch or event path.
3. Delete the raw inbox branch after recording a content-free incident note.
4. Rotate any exposed credential through its owning system.
5. Determine whether the schema or skill instruction can prevent recurrence.

Questions or deletion requests go to the skills repository maintainers. The
installation UUID is stored in `%LOCALAPPDATA%\AgentSkills\config.json` and is
the identifier needed to locate a machine's inbox branches.
