"""REST and SSE API over ``ctx.agents``, under ``/api`` on ``ctx.http``.

| method | path | body | response |
|--------|------|------|----------|
| GET    | ``/health`` |  | generation, restart state, model, workspace |
| GET    | ``/plugins`` |  | loader entries, installed bundles |
| POST   | ``/plugins/install`` | ``{"path"}`` | install a bundle directory; restart scheduled |
| POST   | ``/plugins/install`` | ``{"package", "index_url"?}`` | install a PyPI package; restart scheduled |
| PUT    | ``/plugins/bundles/{name}`` | ``{"enabled"}`` | enable or disable a profile-installed or optional bundle |
| DELETE | ``/plugins/bundles/{name}`` |  | uninstall a profile-installed bundle |
| PUT    | ``/plugins/entries/{id}`` | ``{"enabled"}`` | enable or disable an entry of a profile-installed bundle |
| POST   | ``/restart`` |  | restart after running turns (supervised) |
| GET    | ``/sessions`` |  | sessions |
| POST   | ``/sessions`` | ``{"title"?, "model"?, "workspace"?, "mode"?, "preset"?}`` | session |
| GET    | ``/sessions/{id}`` |  | session, busy, messages, pending approvals |
| POST   | ``/sessions/{id}/messages`` | ``{"content", "images"?}`` | SSE run events |
| GET    | ``/workspaces/search`` | ``q``, ``root``?, ``limit``?, ``hidden``?, ``fuzzy``? | paths matching ``q`` |
| POST   | ``/sessions/{id}/approvals`` | ``{"decisions": [decision]}`` | SSE run events |
| POST   | ``/sessions/{id}/compact`` |  | SSE of a manual compaction run (``compact``, ``done``) |
| POST   | ``/sessions/{id}/answers`` | ``{"answers", "interrupt_id"?}`` | SSE of the resumed run |
| POST   | ``/sessions/{id}/cancel`` |  | ``{"cancelled"}`` |
| DELETE | ``/sessions/{id}`` |  | ``{"deleted"}`` |
| GET    | ``/sessions/{id}/stream`` |  | SSE of the running turn; 204 when idle |
| PUT    | ``/sessions/{id}`` | ``{"title"}`` | rename the session |
| PUT    | ``/sessions/{id}/model`` | ``{"model"}`` | select ``route:model`` for the session |
| PUT    | ``/sessions/{id}/mode`` | ``{"mode"}`` | permission mode; next run |
| PUT    | ``/sessions/{id}/preset`` | ``{"preset"}`` | agent preset; next run |
| GET    | ``/agent`` |  | presets, modes, defaults for new sessions |
| PUT    | ``/settings/agent`` | ``{"default_preset"?, "default_mode"?}`` | defaults for new sessions; persisted |
| GET    | ``/workspaces`` |  | default and recent workspaces, picker kind |
| POST   | ``/workspaces/pick`` | ``{"path"?: prompt}`` | OS folder dialog on this machine; null = cancelled |
| POST   | ``/workspaces`` | ``{"path"}`` | validate and remember a workspace |
| PUT    | ``/workspaces`` | ``{"path", "name"}`` | display name of a workspace |
| DELETE | ``/workspaces?path=`` |  | forget a workspace |
| POST   | ``/workspaces/browse`` | ``{"path"?}`` | one directory level for the picker |
| GET    | ``/workspaces/files`` | ``?path=&root=`` | directory entries inside a workspace |
| GET    | ``/workspaces/file`` | ``?path=&root=&limit=`` | text of a file inside a workspace |
| GET    | ``/workspaces/file/raw`` | ``?path=&root=`` | bytes of a file inside a workspace (images) |
| GET    | ``/sessions/{id}/changes`` |  | changed-file summaries per turn |
| GET    | ``/sessions/{id}/turns`` |  | per-turn stats and trajectory records |
| GET    | ``/sessions/{id}/changes/{run}/diff`` | ``?index=`` | hunks of one listed file, lines highlighted |
| GET    | ``/settings/mcp`` |  | MCP servers (secrets masked) and status |
| PUT    | ``/settings/mcp`` | ``{"servers": {name: server}}`` | replace the MCP server list; restart scheduled |
| POST   | ``/highlight`` | ``{"items": [{code, lang?, filename?}]}`` | Pygments token spans per item |
| GET    | ``/highlight.css`` |  | token colors for light and dark themes |
| GET    | ``/models`` |  | selector directory: routes, models, default |
| GET    | ``/settings/models`` |  | routes with credential state, catalog |
| PUT    | ``/settings/models`` | ``{"default"}`` | default model for new sessions |
| PUT    | ``/settings/models/{route}`` | ``route settings`` | create or edit a route; applies at once |
| DELETE | ``/settings/models/{route}`` |  | remove a route and its stored credential |
| POST   | ``/settings/models/{route}/discover`` | ``route settings`` | model ids served by the endpoint |
| POST   | ``/settings/models/{route}/test`` | ``route settings`` | one short completion with ``model`` |

``/plugins/bundles/{name}`` and ``/plugins/entries/{id}``: a built-in bundle or entry answers 409.
``/sessions/{id}/messages``: ``images`` are data URLs; ``@path`` references expand (:mod:`.references`).
``/sessions/{id}/answers``: answers a pending ask_user_question.

| status | condition                                 |
|--------|-------------------------------------------|
| 404    | unknown session                           |
| 409    | running turn, or approvals pending/absent |
| 422    | images sent to a model without image input |
| 503    | restart pending (``Retry-After: 2``)      |

``decision``: ``{"type": "approve"}`` or ``{"type": "reject"}``.

``route settings``: ``{"type"?, "title"?, "protocol"?, "base_url"?, "api_key"?, "models"?, "options"?, "model"?}``.
A typed ``api_key`` is stored in the profile credential store under ``<ROUTE>_API_KEY`` and referenced from the
configuration; ``""`` deletes it; absent keeps it. Values are never returned. Saved settings apply to the next
model request without a restart.

| module                 | content                                                        |
|------------------------|----------------------------------------------------------------|
| ``plugin``             | ``Config``, router composition, ``apply``                      |
| ``models``             | request bodies                                                 |
| ``routes_harness``     | health, plugins, restart, MCP settings, highlight              |
| ``routes_sessions``    | sessions, SSE runs, turns, changes                             |
| ``routes_workspaces``  | workspace registry and files                                   |
| ``routes_settings``    | agent defaults, compaction, model routes                       |
| ``references``         | ``@path`` references                                           |
| ``highlight``          | Pygments highlighting                                          |
"""

from __future__ import annotations

from .plugin import Config, apply, inject, name

__all__ = ["Config", "apply", "inject", "name"]
