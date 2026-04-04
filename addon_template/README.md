# Third-Party Addon Template

Copy the `hello_addon` folder into your launcher addons directory and rename it.

The launcher looks for addons in:
- portable/dev mode: the `addons` folder next to `launcher_config.json`
- standard installs: the `addons` folder inside the launcher config directory

Each addon needs:
- `addon.json` for metadata and launcher actions
- a Python entrypoint such as `main.py`

Minimal contract:
- `addon.json` defines `id`, `name`, `version`, `description`, `entrypoint`, and `actions`
- `main.py` should expose `handle_action(action_id, inputs, context)`

Available action input types:
- `text`
- `number`
- `checkbox`
- `password`

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
