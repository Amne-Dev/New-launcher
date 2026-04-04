def handle_action(action_id, inputs, context):
    if action_id == "show_greeting":
        message = str(inputs.get("message") or "Hello from my addon!")
        return {
            "status": "success",
            "msg": message
        }

    return {
        "status": "error",
        "msg": f"Unknown action: {action_id}"
    }
