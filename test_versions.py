import minecraft_launcher_lib

print("Fetching Fabric versions...")
try:
    fabric_vers = minecraft_launcher_lib.fabric.get_all_minecraft_versions()
    print(f"Fabric count: {len(fabric_vers)}")
    print(f"Fabric first 5: {fabric_vers[:5]}")
except Exception as e:
    print(f"Fabric error: {e}")

print("\nFetching Forge versions...")
try:
    # list_forge_versions usually lists forge versions for the whole history or returns a map?
    # Let's see what it does.
    forge_vers = minecraft_launcher_lib.forge.list_forge_versions()
    # It might return a list of build strings like '1.12.2-14.23.5.2859'
    print(f"Forge version count: {len(forge_vers)}")
    print(f"Forge first 5: {forge_vers[:5]}")
except Exception as e:
    print(f"Forge error: {e}")
