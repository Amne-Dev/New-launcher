# Third-Party Addon Template

Use this template to create a third-party addon for New Launcher. Copy the `hello_addon` folder into your launcher addons directory and rename it to a unique addon name.

The launcher looks for addons in:
- portable/dev mode: the `addons` folder next to `launcher_config.json`
- standard installs: the `addons` folder inside the launcher config directory

Each addon needs:
- `addon.json` for metadata and launcher actions
- a Python entrypoint such as `main.py`

Restart or refresh the Addons page after copying an addon so the launcher can discover it. Addons run as local Python code with the same user permissions as the launcher; only install addons you trust.

Minimal contract:
- `addon.json` defines `id`, `name`, `version`, `description`, `entrypoint`, and `actions`
- `main.py` should expose `handle_action(action_id, inputs, context)`

Available action input types:
- `text`
- `number`
- `checkbox`
- `password`

Inputs are passed to the handler in the `inputs` dictionary using the input identifiers defined in `addon.json`.

The addon action can return:
- `{"status": "success", "msg": "Done"}`
- `{"status": "error", "msg": "Something went wrong"}`
- `{"status": "success", "data": {"open_path": "...", "open_url": "...", "refresh_addons": true}}`

The `context` dictionary includes:
- `addon_id`
- `addon_name`
- `addon_dir`
- `data_dir`
- `addons_dir`
- `config_dir`
- `launcher_dir`
- `minecraft_dir`

Keep addon state under `data_dir` rather than modifying launcher configuration files directly. Return a short user-facing message in `msg`, and use `refresh_addons` when an action changes addon-visible state.
