# Roadmap

The project has one job: distribute a small reviewed skill library safely and
return explicit factual corrections through normal review.

## Pilot gates

- Complete the standard-user install and scheduled-task runs in `TESTING.md`
  against real Azure DevOps repositories.
- Verify teammate permissions: read skills, push only the machine's
  `feedback/v1/*` branch, and never push protected skills `main`.
- Exercise expired Git Credential Manager credentials for both repositories.
- Verify Cursor discovers both skills and that their bundled scripts work from
  the installed runtime.
- Correct each skill once, publish the two learnings, aggregate them on a review
  branch, and prove a second aggregation is idempotent.
- Run a five-to-ten-person pilot for two review cycles.

Pilot success means installation is understandable, safe updates never rewrite
local files, failed feedback pushes remain queued, and maintainers receive
useful corrections without prohibited data.

## Consider only after the pilot

- Trigger regression fixtures for skill descriptions.
- Removing uv from the updater if it is not already a team prerequisite.
- A simpler feedback transport if the Git inbox causes real operational pain.
- Additional skills only when a repeated task has a distinct trigger and owner.

Skill packs, usage dashboards, fleet tracking, platform analytics importers,
release channels, and company-wide catalogs are intentionally out of scope.
