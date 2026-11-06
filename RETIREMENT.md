# Legacy teaching proxy retirement

Retired at the owner\x27s request on 6 November 2026. Teaching workflows now use My Teaching Plugin and native Google connections.

All application routes return HTTP 410 with a retirement notice, except GET/HEAD /health, which reports status retired with HTTP 200 so the hosting platform can deploy this shutdown safely. No Google, OpenAI, Qdrant, calendar or document clients are loaded. The old indexing script is disabled.

The owner still needs to pause the hosting service and its uptime monitor, revoke credentials dedicated to this project, and archive this repository. Do not delete or revoke anything shared with active projects. Removing credential files from the current tree does not remove earlier Git history or revoke credentials.

Previous source is retained in Git history for reference. Do not redeploy a historical revision without a separate security and credential review.
