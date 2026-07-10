# Privacy and feedback

Agent Skills collects only explicit factual corrections intended to improve a
shared skill. It does not record ordinary skill use.

## Data collected

When an agent deliberately runs `record-learning`, schema version 1 permits:

- a random installation UUID;
- a random event UUID;
- a UTC timestamp;
- the skill name and skills-repository Git SHA;
- one correction category;
- one single-line factual message of at most 2,000 characters.

The validator rejects unknown fields. Adding a field requires an explicit
schema, privacy, test, and documentation change.

## Data not collected

The system has no invocation, outcome, heartbeat, fleet, adoption, duration, or
productivity events. Do not put any of the following in a learning:

- prompts, responses, reasoning, or conversation transcripts;
- source code, diffs, filenames, repository paths, names, URLs, or branches;
- usernames, email addresses, hostnames, serial numbers, or IP addresses;
- tickets, customer information, credentials, secrets, or internal endpoints.

Learning text is agent-written and untrusted. Review it before merge.

## Storage and access

Unpublished feedback is stored under
`%LOCALAPPDATA%\AgentSkills\feedback\pending`. A successful inbox push deletes
the local pending copy. Invalid local files move to `feedback\quarantine` for
manual inspection or deletion.

Each installation publishes only to
`feedback/v1/<random-installation-uuid>` in the separate inbox repository.
The Git provider may associate normal authentication and audit records with the
push, so the UUID is pseudonymous rather than anonymous.

Maintainers can read inbox branches and fold reviewed text into a normal pull
request. Other teammates need no access to aggregated local state beyond the
reviewed skills repository.

## Retention and deletion

This project does not promise automatic server-side deletion. Inbox branches,
Git-provider audit records, reviewed processed-event IDs, and learnings merged
through a pull request follow the repositories' normal retention and Git
history.

Manual uninstall can delete local configuration, queued feedback, quarantine,
and logs. It does not delete data already pushed. The installation UUID in
`%LOCALAPPDATA%\AgentSkills\config.json` is the identifier a maintainer needs
to locate a machine's feedback branch for a deletion request.

If a learning contains prohibited or sensitive content, do not copy it into a
pull request or issue. Notify the repository maintainers, delete the affected
inbox branch where possible, and rotate any exposed credential through its
owning system.
